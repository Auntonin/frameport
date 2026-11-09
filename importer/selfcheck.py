"""Explicit offline release check. Uses synthetic fixtures and a loopback API only."""
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch
from openpyxl import Workbook
from PIL import Image
from .appearance import BACKGROUND, TEXT
from .native_webp import ENCODER
from .runtime import ASSETS, VERSION

class Fixture(BaseHTTPRequestHandler):
    uploads = []
    def log_message(self, *_args):
        pass
    def reply(self, status, data, cookie=False):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if cookie:
            self.send_header("Set-Cookie", "session=fixture-admin; HttpOnly; Path=/")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    def do_GET(self):
        if self.path == "/login":
            return self.reply(200, {"local_test": True}, cookie=True)
        if self.path == "/example-api/session":
            if "session=fixture-admin" not in self.headers.get("Cookie", ""):
                return self.reply(401, {})
            return self.reply(200, {"user": {"role": "ADMIN", "email": "fixture@example.test"}})
        self.reply(404, {})
    def do_POST(self):
        content = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path != "/example-api/items" or "session=fixture-admin" not in self.headers.get("Cookie", ""):
            return self.reply(403, {})
        message = BytesParser(policy=policy.default).parsebytes(
            ("Content-Type: " + self.headers["Content-Type"] + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + content)
        self.uploads.append({part.get_param("name", header="content-disposition"): part.get_payload(decode=True) for part in message.iter_parts() if part.get_content_type() != "image/webp"})
        self.image_parts = [part for part in message.iter_parts() if part.get_content_type() == "image/webp"]
        self.server.image_bytes = [part.get_payload(decode=True) for part in self.image_parts]
        self.reply(201, {"data": {"id": "fixture-location"}})

def run_selfcheck(application, report_path):
    report = {"version": VERSION, "frozen": bool(getattr(sys, "frozen", False)), "ok": False}
    root = None
    server = None
    try:
        with TemporaryDirectory(prefix="frameport-release-check-") as temporary:
            directory = Path(temporary)
            images = directory / "images"
            images.mkdir()
            originals = []
            for index in range(5):
                image = images / (f"IMG_{index + 1}.jpg" if index == 0 else f"IMG_{index + 1}.webp")
                Image.new("RGB", (128, 96), (index * 40, 20, 30)).save(image)
                originals.append(image.read_bytes())
            book = Workbook()
            book.active.append(["Ignored", "Coordinates", "Name", "Description"])
            book.active.append([999, "13.65,100.49", "Release fixture", "Synthetic data"])
            excel = directory / "input.xlsx"
            book.save(excel)
            book.close()
            root = tk.Tk()
            root.withdraw()
            callback_errors = []
            root.report_callback_exception = lambda *error: callback_errors.append(str(error))
            gui = application(root)
            assert root.cget("background") == BACKGROUND
            assert ttk.Style(root).lookup("TLabel", "foreground") == TEXT
            assert "disabled" in gui.stop_button.state()
            assert (ASSETS / "assets/app.ico").is_file()
            report["theme"] = "black-white"
            report["native_webp"] = subprocess.check_output([str(ENCODER), "-version"], creationflags=subprocess.CREATE_NO_WINDOW).decode().strip()
            Fixture.uploads = []
            server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
            Thread(target=server.serve_forever, daemon=True).start()
            gui.url.set(f"http://127.0.0.1:{server.server_port}")
            gui.excel.set(str(excel))
            gui.images.set(str(images))
            gui.header.set(True)
            def wait_for_work():
                deadline = time.monotonic() + 60
                while gui.busy and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
                assert not gui.busy, "Background operation timed out"
                assert not callback_errors, callback_errors
            with patch("tkinter.messagebox.showerror") as errors:
                gui.browser_account()
                wait_for_work()
                assert gui.auth is not None, "Browser session was not received"
                report["browser_session"] = "ADMIN via HttpOnly loopback cookie"
                with patch("tkinter.messagebox.askyesno", return_value=True):
                    gui.start()
                    wait_for_work()
                    gui.start()
                    wait_for_work()
                assert not errors.called, str(errors.call_args)
            assert len(Fixture.uploads) == 1, "Resume duplicated upload"
            payload = Fixture.uploads[0]
            assert payload["latitude"] == b"13.65" and payload["longitude"] == b"100.49"
            assert payload["name"] == b"Release fixture" and payload["description"] == b"Synthetic data"
            assert len(server.image_bytes) == 5
            assert server.image_bytes[1:] == originals[1:], "Ready WebP bytes changed"
            assert all(image["bytes"] <= 5 * 1024 * 1024 for image in gui.items[0]["images"])
            gui.table.selection_set("0")
            gui.details()
            root.update()
            previews = [child for child in root.winfo_children() if isinstance(child, tk.Toplevel)]
            assert len(previews) == 1 and len(previews[0].photos) == 5
            report.update(ok=True, uploaded_locations=1, uploaded_images=5, resume="no duplicates", ready_webp="unchanged", mapping="B=lat,long C=name D=description A=ignored", preview="5 thumbnails", callback_errors=callback_errors)
            root.after_cancel(gui.poll_id)
    except Exception:
        import traceback
        report["error"] = traceback.format_exc()
    finally:
        if root is not None:
            root.destroy()
        if server is not None:
            server.shutdown()
            server.server_close()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if not report["ok"]:
        raise SystemExit(1)
