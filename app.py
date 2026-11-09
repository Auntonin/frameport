"""Standalone Windows importer. Credentials are kept only in process memory."""
import os
from pathlib import Path
from queue import Empty, Queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from importer.interface import build_interface, show_details
from importer.appearance import BACKGROUND
from importer.runtime import ASSETS, APP_DIRECTORY, VERSION, data_directory, initialize_data, read_preferences, save_preferences

from importer.api import WebsiteApi, load_profile, target_url
from importer.browser_login import AuthenticatedSession, browser_login
from importer.plan import prepare, read_plan
from importer.runner import Journal, destination_key, upload_all
from importer.settings_dialog import show_settings

ROOT = ASSETS
DATA = data_directory()


class ImporterApp:
    def __init__(self, root):
        self.root = root
        root.title(f"FramePort · {VERSION}")
        root.geometry("1120x820")
        root.minsize(920, 700)
        root.configure(background=BACKGROUND)
        self.queue = Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.items = []
        self.prepared_profile = None
        self.profile_path = ROOT / "profiles/example.json"
        DATA.mkdir(parents=True, exist_ok=True)
        self.journal = Journal(DATA / "history.sqlite3")
        self.url = tk.StringVar(value="")
        self.email = tk.StringVar()
        self.password = tk.StringVar()
        self.cookie = tk.StringVar()
        self.auth = None
        self.account_status = tk.StringVar(value="ยังไม่ได้เข้าสู่ระบบ")
        self.excel = tk.StringVar()
        self.images = tk.StringVar()
        self.header = tk.BooleanVar(value=True)
        self.lossless = tk.BooleanVar(value=True)
        self.message = tk.StringVar(value="เข้าสู่ระบบ → เลือกไฟล์และภาพ → เริ่มนำเข้า · กดตรวจรายการเมื่อต้องการ Preview")
        try:
            preferences = read_preferences(DATA)
            for key, variable in (("url", self.url), ("excel", self.excel), ("images", self.images), ("header", self.header), ("lossless", self.lossless)):
                if key in preferences:
                    variable.set(preferences[key])
            if preferences.get("custom_profile") and Path(preferences["custom_profile"]).is_file():
                self.profile_path = Path(preferences["custom_profile"])
        except (OSError, ValueError):
            self.message.set("อ่านการตั้งค่าเดิมไม่สำเร็จ กรุณาเลือกเว็บไซต์และไฟล์อีกครั้ง")
        self.build()
        self.poll_id = root.after(100, self.poll)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def build(self):
        build_interface(self)

    def details(self, _event=None):
        show_details(self)

    def invalidate(self):
        self.items = []
        self.prepared_profile = None
        if hasattr(self, "table"):
            self.table.delete(*self.table.get_children())

    def pick_excel(self):
        if not self.busy:
            path = filedialog.askopenfilename(filetypes=[("Excel / CSV", "*.xlsx *.csv")])
            if path:
                self.excel.set(path)
                self.header.set(Path(path).suffix.lower() != ".csv")

    def pick_images(self):
        if not self.busy:
            path = filedialog.askdirectory()
            if path:
                self.images.set(path)

    def pick_profile(self):
        if not self.busy:
            path = filedialog.askopenfilename(initialdir=ROOT / "profiles", filetypes=[("API profile", "*.json")])
            if path:
                try:
                    profile = load_profile(path)
                    self.profile_path = Path(path)
                    self.auth = None
                    self.account_status.set("เข้าสู่ระบบอีกครั้งหลังเปลี่ยน API profile")
                    self.invalidate()
                    self.message.set(f"เลือก profile {profile['name']}")
                except Exception as error:
                    messagebox.showerror("Profile", str(error))

    def remember_settings(self):
        preferences = {"url": self.url.get(), "excel": self.excel.get(), "images": self.images.get(),
                       "header": self.header.get(), "lossless": self.lossless.get()}
        if self.profile_path != ROOT / "profiles/example.json":
            preferences["custom_profile"] = str(self.profile_path)
        try:
            save_preferences(DATA, preferences)
        except OSError:
            self.message.set("บันทึกการตั้งค่าไม่ได้ แต่ยังใช้งานต่อได้")

    def work(self, function):
        if self.busy:
            return
        self.remember_settings()
        self.busy = True
        self.cancel.clear()
        self.stop_button.state(["!disabled"])
        self.activity.start(15)
        for button in self.controls:
            button.state(["disabled"])
        def run():
            try:
                result = function()
                self.queue.put(("result", result))
            except Exception as error:
                self.queue.put(("error", str(error)))
            finally:
                self.queue.put(("done", None))
        threading.Thread(target=run, daemon=True).start()

    def progress(self, text):
        self.queue.put(("progress", text))

    def credentials(self):
        return self.url.get(), load_profile(self.profile_path), self.email.get(), self.password.get(), self.cookie.get()

    def login(self, credentials):
        url, profile, email, password, cookie = credentials
        api = WebsiteApi(url, profile)
        try:
            if self.auth is not None:
                self.auth.apply(api)
                identity = api.check_admin()
            elif email or cookie:
                identity = api.login(email, password, cookie)
            else:
                raise ValueError("กรุณากดเข้าสู่ระบบผ่านเว็บไซต์ก่อนเริ่มนำเข้า")
            self.progress(f"ตรวจสิทธิ์ ADMIN สำเร็จ · {identity} · {api.base_url}")
            return api
        except Exception:
            api.close()
            self.queue.put(("auth_expired", None))
            raise

    def check_account(self):
        try:
            credentials = self.credentials()
            def check():
                url, profile, email, password, cookie = credentials
                api = WebsiteApi(url, profile)
                try:
                    identity = api.login(email, password, cookie)
                    cookies = [{"name": value.name, "value": value.value, "domain": value.domain, "path": value.path, "secure": value.secure, "expires": value.expires or -1} for value in api.session.cookies]
                    return AuthenticatedSession(api.base_url, profile, identity, cookies, cookie)
                finally:
                    api.close()
            self.work(check)
        except Exception as error:
            messagebox.showerror("ตั้งค่า", str(error))

    def browser_account(self):
        try:
            url, profile = self.url.get(), load_profile(self.profile_path)
            self.auth = None
            self.account_status.set("รอเข้าสู่ระบบในเบราว์เซอร์…")
            self.work(lambda: browser_login(url, profile, DATA / "browser", self.cancel, self.progress))
        except Exception as error:
            messagebox.showerror("เข้าสู่ระบบ", str(error))

    def preview(self):
        try:
            excel, directory = Path(self.excel.get()), Path(self.images.get())
            profile = load_profile(self.profile_path)
            header, lossless = self.header.get(), self.lossless.get()
            self.invalidate()
            def run():
                plan = read_plan(excel, directory, profile, header)
                items = prepare(plan, DATA / "webp", profile, lossless, self.cancel, self.progress, export_files=False)
                return items, profile
            self.work(run)
        except Exception as error:
            messagebox.showerror("Preview", str(error))

    def open_output(self):
        if not self.items:
            messagebox.showinfo("โฟลเดอร์ WebP", "กดตรวจรายการและภาพให้เสร็จก่อน")
            return
        os.startfile(str(Path(self.items[0]["images"][0]["path"]).parent))

    def start(self):
        if self.busy:
            return
        try:
            credentials = self.credentials()
            if self.auth is None:
                raise ValueError("กรุณากดเข้าสู่ระบบผ่านเว็บไซต์ก่อนเริ่มนำเข้า")
            target = target_url(credentials[0])
            excel, directory = Path(self.excel.get()), Path(self.images.get())
            header, lossless = self.header.get(), self.lossless.get()
            profile = credentials[1]
            if not messagebox.askyesno("ยืนยันเว็บไซต์ปลายทาง", f"ตรวจข้อมูลและนำเข้าไฟล์จาก\n{excel.name}\nไปยัง {target} ใช่ไหม?"):
                return
            def run():
                api = self.login(credentials)
                try:
                    plan = read_plan(excel, directory, profile, header)
                    items = prepare(plan, DATA / "webp", profile, lossless, self.cancel, self.progress, export_files=False)
                    self.queue.put(("prepared", (items, profile)))
                    upload_all(api, items, self.journal, self.cancel, self.progress)
                finally:
                    api.close()
            self.work(run)
        except Exception as error:
            messagebox.showerror("นำเข้า", str(error))

    def refresh(self):
        self.table.delete(*self.table.get_children())
        if self.auth is not None and self.url.get().strip().rstrip("/") != self.auth.target:
            self.auth = None
            self.account_status.set("เว็บไซต์เปลี่ยน กรุณาเข้าสู่ระบบอีกครั้ง")
        try:
            api = WebsiteApi(self.url.get(), self.prepared_profile or load_profile(self.profile_path))
            target = destination_key(api)
            api.close()
        except Exception:
            target = ""
        labels = {"ready": "พร้อม", "done": "สำเร็จแล้ว", "pending": "ต้องตรวจในเว็บ", "failed": "ส่งไม่สำเร็จ", "retry": "อนุญาตส่งซ้ำ"}
        for index, item in enumerate(self.items):
            location = item["location"]
            state, _ = self.journal.state(target, item["fingerprint"])
            if state == "ready" and any(image.get("over_limit", False) for image in item["images"]):
                labels["oversized"] = "เกินขนาด API"
                state = "oversized"
            self.table.insert("", "end", iid=str(index), values=(item["row"], location["name"], f"{location['latitude']}, {location['longitude']}", ", ".join(image["source"] for image in item["images"]), labels[state]))

    def retry(self):
        selection = self.table.selection()
        if not selection:
            messagebox.showinfo("รายการค้าง", "เลือกรายการในตารางที่ต้องการตรวจสอบ")
            return
        item = self.items[int(selection[0])]
        try:
            api = WebsiteApi(self.url.get(), self.prepared_profile)
            target = destination_key(api)
            api.close()
            if self.journal.state(target, item["fingerprint"])[0] != "pending":
                raise ValueError("รายการนี้ไม่มีคำขอค้าง")
            found = messagebox.askyesnocancel("ตรวจรายการค้างในเว็บไซต์", f"ตรวจ {self.url.get()} แล้วพบว่า\n{item['location']['name']}\nถูกสร้างสำเร็จแล้วหรือยัง?\n\nYes = พบแล้ว บันทึก ID เพื่อข้ามรายการ\nNo = ไม่พบ ต้องการอนุญาตให้ส่งใหม่\nCancel = กลับไปตรวจสอบก่อน")
            if found is True:
                location_id = simpledialog.askstring("ID สถานที่", "วาง ID ของสถานที่ที่ตรวจพบในเว็บไซต์", parent=self.root)
                if location_id and location_id.strip():
                    self.journal.finish(target, item["fingerprint"], "done", location_id.strip())
                    self.refresh()
            elif found is False and messagebox.askyesno("อนุญาตส่งซ้ำ", "ยืนยันว่าไม่พบสถานที่นี้ในเว็บไซต์ และคำขอก่อนหน้าจบแล้วใช่ไหม?"):
                self.journal.allow_retry(target, item["fingerprint"])
                self.refresh()
        except Exception as error:
            messagebox.showerror("รายการค้าง", str(error))

    def poll(self):
        try:
            while True:
                kind, value = self.queue.get_nowait()
                if kind == "result" and value is not None:
                    if isinstance(value, AuthenticatedSession):
                        self.auth = value
                        self.account_status.set(f"Admin · {value.email}")
                        self.message.set("เข้าสู่ระบบสำเร็จ เลือกไฟล์ข้อมูลและโฟลเดอร์ภาพ แล้วกดเริ่มนำเข้า")
                    else:
                        self.items, self.prepared_profile = value
                        self.refresh()
                        oversized = sum(image.get("over_limit", False) for item in self.items for image in item["images"])
                        if oversized:
                            self.message.set(f"เตรียมครบ {len(self.items)} สถานที่ · มี {oversized} ภาพเกินขนาด API ต้องเพิ่มขนาดที่เว็บไซต์รับก่อนนำเข้า · ดับเบิลคลิกเพื่อดูภาพ")
                        else:
                            self.message.set(f"พร้อม {len(self.items)} สถานที่ · ดับเบิลคลิกแต่ละแถวเพื่อตรวจภาพทั้ง 5 รูป")
                elif kind == "prepared":
                    self.items, self.prepared_profile = value
                    self.refresh()
                elif kind in {"progress", "error"}:
                    self.message.set(value)
                    self.log.configure(state="normal")
                    self.log.insert("end", value + "\n")
                    self.log.see("end")
                    self.log.configure(state="disabled")
                    if kind == "error":
                        if self.auth is None:
                            self.account_status.set("ยังไม่ได้เข้าสู่ระบบ")
                        messagebox.showerror("หยุดการทำงาน", value)
                elif kind == "done":
                    self.busy = False
                    self.activity.stop()
                    self.stop_button.state(["disabled"])
                    for button in self.controls:
                        button.state(["!disabled"])
                    self.refresh()
                elif kind == "auth_expired":
                    self.auth = None
                    self.account_status.set("กรุณาเข้าสู่ระบบอีกครั้ง")
        except Empty:
            pass
        self.poll_id = self.root.after(100, self.poll)

    def close(self):
        if self.busy:
            self.cancel.set()
            messagebox.showinfo("กำลังหยุด", "รอให้รายการปัจจุบันจบก่อนปิด เพื่อบันทึกผลการนำเข้า")
            return
        self.remember_settings()
        self.root.after_cancel(self.poll_id)
        self.root.destroy()


def main():
    global DATA
    import sys
    if "--self-check" in sys.argv:
        from importer.selfcheck import run_selfcheck
        report = Path(sys.argv[sys.argv.index("--self-check") + 1]).resolve()
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(prefix="frameport-isolated-check-") as temporary:
            DATA = Path(temporary) / "state"
            run_selfcheck(ImporterApp, report)
        return
    initialize_data(DATA, [])
    root = tk.Tk()
    icon = ROOT / "assets/app.ico"
    if icon.is_file():
        root.iconbitmap(str(icon))
    ImporterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
