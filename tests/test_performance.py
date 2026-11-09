import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event, Lock
import time
import unittest
from unittest.mock import patch

from PIL import Image

from importer.api import ApiError, WebsiteApi, load_profile
from importer.conversion import fit_webp
from importer.plan import Location, prepare
from importer.resources import choose_workers
from importer.files import cache_job_lock
from importer.runner import Journal, upload_all

PROFILE = load_profile(Path(__file__).resolve().parents[1] / "profiles/example.json")


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        files = []
        for index in range(10):
            path = self.directory / f"IMG_{index + 1}.jpg"
            Image.new("RGB", (160, 120), (index * 20, 30, 90)).save(path)
            files.append(path)
        self.plan = [Location(2, "Library/name", "Books", 13.65, 100.49, files[:5]),
                     Location(3, "Park", "Trees", 13.66, 100.50, files[5:])]
        self.cache = self.directory / "cache"

    def run_prepare(self, **kwargs):
        return prepare(self.plan, self.cache, PROFILE, True, Event(), lambda _text: None, **kwargs)

    def test_warm_run_uses_every_cached_image_without_encoding_again(self):
        first = self.run_prepare()
        with patch("importer.conversion.fit_webp", side_effect=AssertionError("unexpected encoding")):
            second = self.run_prepare()
        self.assertEqual(first, second)
        stats = json.loads((self.directory / "performance.json").read_text())
        self.assertEqual(stats["cache_hits"], 10)

    def test_metadata_edit_reuses_images_and_preserves_export_order(self):
        self.run_prepare()
        self.plan[0].name = "New name"
        self.plan[0].description = "New description"
        with patch("importer.conversion.fit_webp", side_effect=AssertionError("unexpected encoding")):
            prepared = self.run_prepare()
        for item, original in zip(prepared, self.plan):
            self.assertEqual([image["source"] for image in item["images"]], [path.name for path in original.files])
            folder = Path(item["images"][0]["path"]).parent
            self.assertEqual(len(list(folder.glob("*.webp"))), 5)
            self.assertEqual([Path(image["path"]).name[:3] for image in item["images"]], [f"{number:02d}-" for number in range(1, 6)])
        manifest = Path(prepared[0]["images"][0]["path"]).parent.parent / "manifest.json"
        self.assertEqual(json.loads(manifest.read_text(encoding="utf-8")), prepared)

    def test_corrupt_cache_reencodes_only_the_affected_image(self):
        self.run_prepare()
        next(self.cache.glob("*.webp")).write_bytes(b"corrupted")
        with patch("importer.conversion.fit_webp", wraps=fit_webp) as encode:
            self.run_prepare()
        self.assertEqual(encode.call_count, 1)
        self.assertEqual(json.loads((self.directory / "performance.json").read_text())["cache_hits"], 9)

    def test_cancel_keeps_completed_image_for_resume(self):
        cancel = Event()
        def stop_after_one(*args, **kwargs):
            result = fit_webp(*args, **kwargs)
            cancel.set()
            return result
        with patch("importer.conversion.fit_webp", side_effect=stop_after_one):
            with self.assertRaises(ValueError):
                prepare(self.plan, self.cache, PROFILE, True, cancel, lambda _text: None, workers=1)
        with patch("importer.conversion.fit_webp", wraps=fit_webp) as encode:
            self.run_prepare(workers=1)
        self.assertEqual(encode.call_count, 9)

    def test_encoder_calls_overlap_and_results_stay_in_original_order(self):
        barrier = Barrier(2)
        lock = Lock()
        calls = 0
        active = 0
        peak = 0
        def encode(*args, **kwargs):
            nonlocal calls, active, peak
            with lock:
                calls += 1
                number = calls
                active += 1
                peak = max(peak, active)
            try:
                if number <= 2:
                    barrier.wait(timeout=5)
                time.sleep(0.01)
                return fit_webp(*args, **kwargs)
            finally:
                with lock:
                    active -= 1
        with patch("importer.plan.choose_workers", return_value=2), patch("importer.conversion.fit_webp", side_effect=encode):
            prepared = self.run_prepare()
        self.assertEqual(peak, 2)
        self.assertEqual([item["row"] for item in prepared], [2, 3])
        self.assertEqual([image["source"] for image in prepared[0]["images"]], [path.name for path in self.plan[0].files])

    def test_changed_source_reencodes_only_one_image(self):
        self.run_prepare()
        Image.new("RGB", (160, 120), "white").save(self.plan[0].files[0])
        with patch("importer.conversion.fit_webp", wraps=fit_webp) as encode:
            self.run_prepare()
        self.assertEqual(encode.call_count, 1)

    def test_identical_source_images_share_one_encoder_result_safely(self):
        self.plan[1].files[0].write_bytes(self.plan[0].files[0].read_bytes())
        with patch("importer.conversion.fit_webp", wraps=fit_webp) as encode:
            prepared = self.run_prepare()
        self.assertEqual(encode.call_count, 9)
        self.assertEqual(prepared[0]["images"][0]["sha256"], prepared[1]["images"][0]["sha256"])
        self.assertEqual(prepared[1]["images"][0]["source"], "IMG_6.jpg")

    def test_second_job_cannot_overcommit_the_same_cache(self):
        self.cache.mkdir()
        with cache_job_lock(self.cache):
            with self.assertRaisesRegex(ValueError, "กำลังทำงาน"):
                self.run_prepare()
        self.run_prepare()

    def test_ready_webp_uses_original_files_without_encoder_or_export(self):
        originals = {}
        for location in self.plan:
            for index, source in enumerate(location.files):
                ready = source.with_suffix(".webp")
                Image.new("RGB", (160, 120), (index * 30, 10, 70)).save(ready, format="WEBP")
                location.files[index] = ready
                originals[str(ready.resolve())] = ready.read_bytes()
        with patch("importer.conversion.fit_webp", side_effect=AssertionError("unexpected encoding")), patch("importer.plan.export_prepared", side_effect=AssertionError("unexpected export")):
            prepared = prepare(self.plan, self.cache, PROFILE, True, Event(), lambda _text: None, export_files=False)
        for item in prepared:
            for image in item["images"]:
                self.assertTrue(image["passthrough"])
                self.assertEqual(Path(image["path"]).read_bytes(), originals[image["path"]])
        self.assertEqual(list(self.cache.glob("*.webp")), [])
        self.assertFalse((self.directory / "ready-to-upload").exists())

    def test_editing_a_later_image_during_upload_stops_before_sending_it(self):
        prepared = self.run_prepare()
        api = WebsiteApi("http://localhost:3000", PROFILE)
        self.addCleanup(api.close)
        def first_upload(_item):
            Path(prepared[1]["images"][0]["path"]).write_bytes(b"changed after initial checks")
            return "first-location"
        with patch.object(api, "create", side_effect=first_upload) as create:
            with self.assertRaisesRegex(ApiError, "เปลี่ยนระหว่างนำเข้า"):
                upload_all(api, prepared, Journal(self.directory / "history.sqlite3"), Event(), lambda _text: None)
        self.assertEqual(create.call_count, 1)

    def test_workers_reserve_cpu_and_follow_memory_budget(self):
        gib = 1024 ** 3
        with patch("importer.resources.os.cpu_count", return_value=12), patch("importer.resources.native_available", return_value=False):
            with patch("importer.resources.available_memory", return_value=(24 * gib, 20 * gib)):
                self.assertEqual(choose_workers(250, 5328 * 4000), 11)
                self.assertEqual(choose_workers(250, 5328 * 4000, requested=2), 2)
            with patch("importer.resources.available_memory", return_value=(24 * gib, 4 * gib)):
                self.assertLessEqual(choose_workers(250, 5328 * 4000), 4)
            with self.assertRaises(ValueError):
                choose_workers(10, 100, requested=0)


if __name__ == "__main__":
    unittest.main()
