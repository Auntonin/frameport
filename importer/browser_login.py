"""User-driven login in a dedicated normal browser, with site-scoped session handoff."""
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
from urllib.parse import urlsplit
import socket
import subprocess
import time

import requests

from .api import ApiError, WebsiteApi, target_url


@dataclass
class AuthenticatedSession:
    target: str
    profile: dict
    email: str
    cookies: list[dict]
    cookie_header: str = ""

    def apply(self, api):
        if api.base_url != self.target or api.profile != self.profile:
            raise ApiError("เว็บไซต์เปลี่ยน กรุณากดเข้าสู่ระบบสำหรับเว็บไซต์นี้อีกครั้ง")
        for cookie in self.cookies:
            options = {key: cookie[key] for key in ("domain", "path", "secure") if key in cookie}
            # Python's cookie policy expands single-label localhost hosts internally.
            if urlsplit(self.target).hostname == "localhost" and options.get("domain", "").lstrip(".") == "localhost":
                options["domain"] = "localhost.local"
            if cookie.get("expires", -1) > 0:
                options["expires"] = int(cookie["expires"])
            api.session.cookies.set(cookie["name"], cookie["value"], **options)
        if self.cookie_header:
            api.session.headers["Cookie"] = self.cookie_header


def find_browser():
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "BraveSoftware/Brave-Browser/Application/brave.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ApiError("ไม่พบ Microsoft Edge หรือ Google Chrome กรุณาติดตั้งเบราว์เซอร์ก่อน")


def browser_login(base_url, profile, directory, cancel, progress, timeout=600):
    from playwright.sync_api import sync_playwright

    target = target_url(base_url)
    browser_path = find_browser()
    browser_data = directory / sha256(target.encode()).hexdigest()[:16]
    browser_data.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen([
        str(browser_path), f"--user-data-dir={browser_data.resolve()}",
        f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1",
        "--no-first-run", target + profile.get("login_page", "/login"),
    ])
    progress("เปิดเบราว์เซอร์แล้ว กรุณาเข้าสู่ระบบในหน้าเว็บไซต์ ใช้ Google หรือบัญชีเว็บไซต์ได้")
    deadline = time.monotonic() + timeout
    browser = None
    try:
        with sync_playwright() as playwright:
            while not cancel.is_set() and time.monotonic() < deadline:
                if process.poll() is not None:
                    raise ApiError("ปิดเบราว์เซอร์ก่อนเข้าสู่ระบบสำเร็จ กรุณากดเข้าสู่ระบบอีกครั้ง")
                try:
                    browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=1500)
                    break
                except Exception:
                    cancel.wait(0.5)
            if browser is None:
                raise ApiError("หยุดการเข้าสู่ระบบ หรือเชื่อมต่อเบราว์เซอร์ไม่สำเร็จ")
            previous = None
            try:
                context = browser.contexts[0]
                while not cancel.is_set() and time.monotonic() < deadline:
                    if not browser.is_connected() or not context.pages:
                        raise ApiError("เบราว์เซอร์ถูกปิด กรุณาเข้าสู่ระบบอีกครั้ง")
                    cookies = context.cookies([target + profile["session_path"], target + profile["create_path"]])
                    api = WebsiteApi(target, profile)
                    try:
                        session = AuthenticatedSession(target, profile, "", cookies)
                        session.apply(api)
                        session.email = api.check_admin(timeout=(3, 5))
                        return session
                    except (ApiError, requests.RequestException) as error:
                        status = "รอเข้าสู่ระบบในเบราว์เซอร์"
                        if isinstance(error, ApiError) and "ADMIN" in str(error):
                            status = "บัญชีที่เข้าสู่ระบบยังไม่มีสิทธิ์ Admin กรุณาเปลี่ยนบัญชีในเว็บไซต์"
                        if status != previous:
                            progress(status)
                            previous = status
                    finally:
                        api.close()
                    cancel.wait(1)
                raise ApiError("หยุดการเข้าสู่ระบบ หรือหมดเวลารอ กรุณาลองใหม่")
            finally:
                if browser.is_connected():
                    browser.close()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
