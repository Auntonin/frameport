from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from openpyxl import Workbook
from PIL import Image

import app


class GuiTests(unittest.TestCase):
    def test_browser_login_returns_admin_and_changing_site_clears_session(self):
        from importer.browser_login import AuthenticatedSession
        from importer.api import load_profile
        with TemporaryDirectory() as directory:
            root = tk.Tk()
            root.withdraw()
            callback_errors = []
            root.report_callback_exception = lambda *error: callback_errors.append(error)
            try:
                with patch.object(app, "DATA", Path(directory) / "data"):
                    gui = app.ImporterApp(root)
                    profile = load_profile(gui.profile_path)
                    session = AuthenticatedSession(gui.url.get(), profile, "admin@example.test", [])
                    with patch.object(app, "browser_login", return_value=session):
                        gui.browser_account()
                        deadline = time.monotonic() + 5
                        while gui.busy and time.monotonic() < deadline:
                            root.update()
                            time.sleep(0.01)
                    self.assertEqual(callback_errors, [])
                    self.assertIs(gui.auth, session)
                    self.assertIn("admin@example.test", gui.account_status.get())
                    gui.url.set("https://another.example")
                    gui.refresh()
                    self.assertIsNone(gui.auth)
            finally:
                if "gui" in locals():
                    root.after_cancel(gui.poll_id)
                root.destroy()

    def test_start_uploads_ready_webp_without_requiring_preview(self):
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from test_importer import FakeWebsite
        from importer.api import load_profile
        from importer.browser_login import AuthenticatedSession
        FakeWebsite.uploads = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeWebsite)
        Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with TemporaryDirectory() as directory:
            path = Path(directory)
            images = path / "ready"
            images.mkdir()
            book = Workbook()
            book.active.append(["A", "B", "C", "D"])
            book.active.append([None, "13.65,100.49", "Ready location", "Description"])
            excel = path / "locations.xlsx"
            book.save(excel)
            book.close()
            originals = []
            for index in range(5):
                image = images / f"IMG_{index + 1}.webp"
                Image.new("RGB", (80, 40), (index * 40, 10, 20)).save(image, format="WEBP")
                originals.append(image.read_bytes())
            root = tk.Tk()
            root.withdraw()
            callback_errors = []
            root.report_callback_exception = lambda *error: callback_errors.append(error)
            try:
                with patch.object(app, "DATA", path / "data"), patch.object(app, "ROOT", path):
                    gui = app.ImporterApp(root)
                    gui.profile_path = Path(app.__file__).parent / "profiles/example.json"
                    gui.url.set(f"http://127.0.0.1:{server.server_port}")
                    gui.excel.set(str(excel))
                    gui.header.set(True)
                    gui.images.set(str(images))
                    gui.auth = AuthenticatedSession(gui.url.get(), load_profile(gui.profile_path), "admin@example.test", [], "session=admin")
                    with patch.object(app.messagebox, "askyesno", return_value=True), patch.object(app.messagebox, "showerror") as error:
                        gui.start()
                        deadline = time.monotonic() + 10
                        while gui.busy and time.monotonic() < deadline:
                            root.update()
                            time.sleep(0.01)
                        self.assertFalse(gui.busy)
                        self.assertEqual(callback_errors, [])
                        error.assert_not_called()
                    self.assertEqual(len(FakeWebsite.uploads), 1)
                    uploaded = [part[2] for part in FakeWebsite.uploads[0] if part[0] == "images"]
                    self.assertEqual(uploaded, originals)
                    self.assertEqual(len(gui.items), 1)
                    self.assertFalse((path / "ready-to-upload").exists())
            finally:
                if "gui" in locals():
                    root.after_cancel(gui.poll_id)
                root.destroy()

    def test_choose_inputs_preview_and_inspect_five_images(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            images = path / "images"
            images.mkdir()
            book = Workbook()
            book.active.append(["Number", "Coordinates", "Name", "Description"])
            book.active.append([77, "13.65,100.49", "Library", "Books"])
            excel = path / "locations.xlsx"
            book.save(excel)
            book.close()
            for index in range(5):
                Image.new("RGB", (80, 40), "green").save(images / f"IMG_{index}.jpg")
            root = tk.Tk()
            root.withdraw()
            callback_errors = []
            root.report_callback_exception = lambda *error: callback_errors.append(error)
            try:
                with patch.object(app, "DATA", path / "data"), patch.object(app, "ROOT", path):
                    gui = app.ImporterApp(root)
                    gui.profile_path = Path(app.__file__).parent / "profiles/example.json"
                    gui.excel.set(str(excel))
                    gui.header.set(True)
                    self.assertTrue(gui.lossless.get())
                    gui.images.set(str(images))
                    gui.preview()
                    self.assertTrue(gui.busy)
                    self.assertNotIn("disabled", gui.stop_button.state())
                    self.assertTrue(all("disabled" in widget.state() for widget in gui.controls))
                    deadline = time.monotonic() + 10
                    while gui.busy and time.monotonic() < deadline:
                        root.update()
                        time.sleep(0.01)
                    self.assertEqual(callback_errors, [])
                    self.assertFalse(gui.busy)
                    self.assertEqual(root.cget("background"), "#0b0b0b")
                    self.assertIn("disabled", gui.stop_button.state())
                    self.assertEqual(len(gui.items), 1)
                    self.assertEqual(len(gui.items[0]["images"]), 5)
                    self.assertEqual(gui.table.item("0")["values"][1], "Library")
                    gui.table.selection_set("0")
                    gui.details()
                    root.update()
                    windows = [widget for widget in root.winfo_children() if isinstance(widget, tk.Toplevel)]
                    self.assertEqual(len(windows), 1)
                    self.assertEqual(len(windows[0].photos), 5)
                    gui.lossless.set(True)
                    gui.invalidate()
                    self.assertEqual(gui.items, [])
            finally:
                if "gui" in locals():
                    root.after_cancel(gui.poll_id)
                root.destroy()


if __name__ == "__main__":
    unittest.main()
