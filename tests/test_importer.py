from email import policy
import csv
from email.parser import BytesParser
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import patch

from openpyxl import Workbook
from PIL import Image
import requests

from importer.api import ApiError, UncertainUpload, WebsiteApi, load_profile, target_url
from importer.plan import prepare, read_plan, fit_webp
from importer.runner import Journal, destination_key, upload_all

ROOT = Path(__file__).resolve().parents[1]
PROFILE = load_profile(ROOT / "profiles/example.json")


class FakeWebsite(BaseHTTPRequestHandler):
    uploads = []

    def log_message(self, *_args):
        pass

    def reply(self, code, data, cookie=None):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path != "/example-api/session":
            return self.reply(404, {})
        cookie = self.headers.get("Cookie", "")
        role = "ADMIN" if "session=admin" in cookie else "USER"
        self.reply(200, {"user": {"role": role, "email": f"{role}@example.test"}})

    def do_POST(self):
        content = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/example-api/sign-in":
            body = json.loads(content)
            if body["password"] != "correct":
                return self.reply(401, {})
            role = "admin" if body["email"] == "admin@example.test" else "user"
            return self.reply(200, {"data": None}, f"session={role}; HttpOnly; Path=/")
        if self.path != "/example-api/items":
            return self.reply(404, {})
        if "session=admin" not in self.headers.get("Cookie", ""):
            return self.reply(403, {})
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {self.headers['Content-Type']}\r\nMIME-Version: 1.0\r\n\r\n".encode() + content)
        parts = [(part.get_param("name", header="content-disposition"), part.get_content_type(), part.get_payload(decode=True)) for part in message.iter_parts()]
        self.uploads.append(parts)
        self.reply(201, {"data": {"id": f"location-{len(self.uploads)}"}})


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.images = self.directory / "images"
        self.images.mkdir()
        self.excel = self.directory / "locations.xlsx"
        self.rows = [["Number", "Coordinates", "Name", "Description"], [99, "13.65,100.49", "Library", "Books"], [103, "-1,-2", "Park", "Trees"]]
        self.write_excel(self.rows)
        for index in range(1, 11):
            Image.new("RGB", (80, 40), (index, 50, 80)).save(self.images / f"IMG_{index}.jpg")

    def write_excel(self, rows):
        book = Workbook()
        for row in rows:
            book.active.append(row)
        book.save(self.excel)
        book.close()

    def prepared(self):
        return prepare(read_plan(self.excel, self.images, PROFILE), self.directory / "webp", PROFILE, False, Event(), lambda _text: None)

    def test_excel_and_natural_grouping_ignore_nonsequential_ids(self):
        plan = read_plan(self.excel, self.images, PROFILE)
        self.assertEqual(plan[0].latitude, 13.65)
        self.assertEqual(plan[1].longitude, -2)
        self.assertEqual([path.name for path in plan[0].files], [f"IMG_{i}.jpg" for i in range(1, 6)])
        self.assertEqual(plan[1].files[-1].name, "IMG_10.jpg")

    def test_headerless_and_blank_rows(self):
        self.write_excel([self.rows[1], [], self.rows[2]])
        self.assertEqual([item.row for item in read_plan(self.excel, self.images, PROFILE, False)], [1, 3])

    def test_utf8_csv_without_header_preserves_first_location(self):
        path = self.directory / "locations.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow([1, "13.65,100.49", "สวนสุขภาพ", "ทางเดิน"])
            writer.writerow([8, "13.66,100.50", "ห้องสมุด", ""])
        plan = read_plan(path, self.images, PROFILE, False)
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[0].name, "สวนสุขภาพ")
        self.assertEqual(plan[0].row, 1)

    def test_coordinate_errors(self):
        for coordinate in ("", "13", "91,100", "13,181", "nan,1", "a,b", "13,100,1"):
            with self.subTest(coordinate=coordinate):
                self.write_excel([self.rows[0], [1, coordinate, "Name", "Description"], self.rows[2]])
                with self.assertRaises(ValueError):
                    read_plan(self.excel, self.images, PROFILE)

    def test_formula_in_a_ignored_but_formula_in_c_rejected(self):
        self.write_excel([self.rows[0], ["=ROW()", *self.rows[1][1:]], self.rows[2]])
        self.assertEqual(len(read_plan(self.excel, self.images, PROFILE)), 2)
        self.write_excel([self.rows[0], [1, "13,100", "=A2", ""], self.rows[2]])
        with self.assertRaises(ValueError):
            read_plan(self.excel, self.images, PROFILE)

    def test_image_count_and_ambiguous_order(self):
        extra = self.images / "IMG_01.jpg"
        Image.new("RGB", (10, 10)).save(extra)
        with self.assertRaisesRegex(ValueError, "กำกวม"):
            read_plan(self.excel, self.images, PROFILE)
        extra.unlink()
        (self.images / "IMG_10.jpg").unlink()
        with self.assertRaisesRegex(ValueError, "10 ภาพ"):
            read_plan(self.excel, self.images, PROFILE)

    def test_full_resolution_webp_repeatable_hash_and_strip_orientation(self):
        path = self.images / "IMG_1.jpg"
        exif = Image.Exif()
        exif[274] = 6
        Image.new("RGB", (80, 40), "green").save(path, exif=exif)
        before = path.read_bytes()
        first = self.prepared()
        second = self.prepared()
        self.assertEqual(first, second)
        with Image.open(first[0]["images"][0]["path"]) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (40, 80))
            self.assertFalse(image.getexif())
        self.assertEqual(path.read_bytes(), before)

    def test_mpo_jpg_uses_full_resolution_primary_image_and_preserves_source(self):
        path = self.images / "IMG_1.jpg"
        primary = Image.new("RGB", (320, 240), "red")
        thumbnail = Image.new("RGB", (80, 60), "blue")
        primary.save(path, format="MPO", save_all=True, append_images=[thumbnail])
        original_bytes = path.read_bytes()
        with Image.open(path) as image:
            self.assertEqual(image.format, "MPO")
            self.assertEqual(image.n_frames, 2)
        items = self.prepared()
        with Image.open(items[0]["images"][0]["path"]) as image:
            self.assertEqual(image.size, (320, 240))
            self.assertEqual(image.format, "WEBP")
            red, green, blue = image.convert("RGB").getpixel((160, 120))
            self.assertGreater(red, blue + 100)
        self.assertEqual(path.read_bytes(), original_bytes)

    def test_actual_animated_webp_disguised_as_jpg_is_rejected(self):
        Image.new("RGB", (80, 40), "red").save(
            self.images / "IMG_1.jpg", format="WEBP", save_all=True,
            append_images=[Image.new("RGB", (80, 40), "blue")], duration=100, loop=0,
        )
        with self.assertRaisesRegex(ValueError, "ภาพเคลื่อนไหว"):
            self.prepared()

    def test_exact_a_b_c_d_mapping_with_missing_and_invalid_column_a(self):
        self.write_excel([
            self.rows[0],
            [None, " 13.650843 , 100.495770 ", "สวนเฉลิมพระเกียรติ", "ที่นั่ง, ริมสวน"],
            ["wrong number", "-13.5, -100.25", "ห้องสมุด", "รายละเอียดสถานที่"],
        ])
        items = read_plan(self.excel, self.images, PROFILE)
        self.assertEqual(items[0].payload(), {
            "latitude": 13.650843, "longitude": 100.495770,
            "name": "สวนเฉลิมพระเกียรติ", "description": "ที่นั่ง, ริมสวน",
        })
        self.assertEqual(items[1].payload(), {
            "latitude": -13.5, "longitude": -100.25,
            "name": "ห้องสมุด", "description": "รายละเอียดสถานที่",
        })

    def test_webp_quality_search_keeps_highest_fitting_candidate(self):
        from unittest.mock import Mock
        image = Mock()
        def encode(filename, **options):
            Path(filename).write_bytes(b"0" * (2000 if options["lossless"] else options["quality"] * 10))
        image.save.side_effect = encode
        output = self.directory / "bounded.webp"
        quality, lossless = fit_webp(image, output, 940, True, Event(), lambda _text: None)
        self.assertEqual(quality, 94)
        self.assertFalse(lossless)
        self.assertEqual(output.stat().st_size, 940)
        self.assertLessEqual(image.save.call_count, 10)

    def test_size_limit_is_enforced_before_every_remote_upload(self):
        items = self.prepared()
        profile = {**PROFILE, "max_image_bytes": 1}
        api = WebsiteApi("http://localhost:3000", profile)
        self.addCleanup(api.close)
        with patch.object(api, "create") as create:
            with self.assertRaisesRegex(ApiError, "เกินข้อจำกัด"):
                upload_all(api, items, Journal(self.directory / "history.sqlite3"), Event(), lambda _text: None)
            create.assert_not_called()

    def test_preparation_stops_if_no_quality_can_fit_at_original_dimensions(self):
        with self.assertRaisesRegex(ValueError, "เกินข้อจำกัด"):
            prepare(read_plan(self.excel, self.images, PROFILE), self.directory / "webp", {**PROFILE, "max_image_bytes": 1}, True, Event(), lambda _text: None)

    def test_lossless_preserves_every_decoded_jpg_pixel(self):
        source = self.images / "IMG_1.jpg"
        pixels = bytes((index * 37) % 256 for index in range(80 * 40 * 3))
        Image.frombytes("RGB", (80, 40), pixels).save(source)
        with Image.open(source) as image:
            expected = image.convert("RGB").tobytes()
        items = prepare(read_plan(self.excel, self.images, PROFILE)[:1], self.directory / "webp", PROFILE, True, Event(), lambda _text: None)
        image = items[0]["images"][0]
        self.assertTrue(image["lossless"])
        self.assertIsNone(image["quality"])
        with Image.open(image["path"]) as converted:
            self.assertEqual(converted.size, (80, 40))
            self.assertEqual(converted.convert("RGB").tobytes(), expected)

    def test_png_transparency_is_preserved(self):
        (self.images / "IMG_1.jpg").unlink()
        Image.new("RGBA", (80, 40), (10, 20, 30, 0)).save(self.images / "IMG_1.png")
        items = self.prepared()
        with Image.open(items[0]["images"][0]["path"]) as image:
            self.assertEqual(image.getpixel((0, 0))[3], 0)

    def test_cancel_preparation(self):
        event = Event()
        event.set()
        with self.assertRaisesRegex(ValueError, "หยุด"):
            prepare(read_plan(self.excel, self.images, PROFILE), self.directory / "webp", PROFILE, False, event, lambda _text: None)

    def test_admin_session_cookie_multipart_and_resume(self):
        FakeWebsite.uploads = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeWebsite)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        api = WebsiteApi(f"http://127.0.0.1:{server.server_port}", PROFILE)
        self.addCleanup(api.close)
        with self.assertRaises(ApiError):
            api.login("admin@example.test", "wrong")
        with self.assertRaisesRegex(ApiError, "ADMIN"):
            api.login("user@example.test", "correct")
        self.assertEqual(api.login("admin@example.test", "correct"), "ADMIN@example.test")
        items = self.prepared()
        journal = Journal(self.directory / "history.sqlite3")
        upload_all(api, items, journal, Event(), lambda _text: None)
        upload_all(api, items, journal, Event(), lambda _text: None)
        self.assertEqual(len(FakeWebsite.uploads), 2)
        parts = FakeWebsite.uploads[0]
        self.assertEqual(len([part for part in parts if part[0] == "images"]), 5)
        self.assertTrue(all(part[1] == "image/webp" for part in parts if part[0] == "images"))
        self.assertIn(("name", "text/plain", b"Library"), parts)
        self.assertIn(("description", "text/plain", b"Books"), parts)
        self.assertIn(("latitude", "text/plain", b"13.65"), parts)
        self.assertIn(("longitude", "text/plain", b"100.49"), parts)
        self.assertEqual({part[0] for part in parts}, {"name", "description", "latitude", "longitude", "images"})
        self.assertEqual(journal.state(destination_key(api), items[0]["fingerprint"]), ("done", "location-1"))

    def test_lost_response_blocks_retry_and_is_target_specific(self):
        api = WebsiteApi("http://localhost:3000", PROFILE)
        self.addCleanup(api.close)
        items = self.prepared()
        journal = Journal(self.directory / "history.sqlite3")
        with patch.object(api, "_request", side_effect=requests.Timeout()):
            with self.assertRaises(UncertainUpload):
                upload_all(api, items, journal, Event(), lambda _text: None)
        with self.assertRaisesRegex(ApiError, "ค้าง"):
            upload_all(api, items, journal, Event(), lambda _text: None)
        target = destination_key(api)
        self.assertEqual(journal.state(target, items[0]["fingerprint"])[0], "pending")
        other = WebsiteApi("https://example.test", PROFILE)
        self.addCleanup(other.close)
        self.assertEqual(journal.state(destination_key(other), items[0]["fingerprint"])[0], "ready")
        journal.allow_retry(target, items[0]["fingerprint"])
        self.assertTrue(journal.reserve(target, items[0]))

    def test_edited_cache_blocks_all_remote_writes(self):
        api = WebsiteApi("http://localhost:3000", PROFILE)
        self.addCleanup(api.close)
        items = self.prepared()
        Path(items[-1]["images"][-1]["path"]).write_bytes(b"changed")
        with patch.object(api, "create") as create:
            with self.assertRaises(ApiError):
                upload_all(api, items, Journal(self.directory / "history.sqlite3"), Event(), lambda _text: None)
            create.assert_not_called()

    def test_target_and_profile_validation(self):
        for value in ("http://example.test", "https://user" + ":password" + "@example.test", "file:///tmp", "https://example.test?q=1"):
            with self.assertRaises(ApiError):
                target_url(value)
        self.assertEqual(target_url("https://example.test/"), "https://example.test")
        path = self.directory / "profile.json"
        path.write_text(json.dumps({**PROFILE, "create_path": "//other.example.test"}))
        with self.assertRaises(ApiError):
            load_profile(path)


if __name__ == "__main__":
    unittest.main()
