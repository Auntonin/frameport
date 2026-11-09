"""Cookie-authenticated HTTP adapter for the website's public API contract."""
from contextlib import ExitStack
import json
from pathlib import Path
from urllib.parse import urlsplit

import requests


class ApiError(Exception):
    pass


class UncertainUpload(ApiError):
    """The server might have committed this request. Never blindly retry it."""


def target_url(value):
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ApiError("URL ต้องเป็น http/https และไม่มีรหัสผ่าน query หรือ fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ApiError("เว็บไซต์ภายนอกต้องใช้ HTTPS")
    return value.strip().rstrip("/")


def load_profile(path):
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("login_path", "session_path", "create_path", "login_page"):
        if key == "login_page" and key not in profile:
            continue
        route = profile[key]
        if not isinstance(route, str) or not route.startswith("/") or route.startswith("//") or ":" in route:
            raise ApiError(f"Profile มีเส้นทางไม่ถูกต้อง {key}")
    for key in ("name", "description", "latitude", "longitude", "images"):
        if not isinstance(profile["fields"][key], str) or not profile["fields"][key].strip():
            raise ApiError("Profile ต้องกำหนดชื่อ fields ครบ")
    if len(set(profile["fields"].values())) != len(profile["fields"]):
        raise ApiError("Profile มีชื่อ fields ซ้ำ")
    if profile["images_per_location"] != 5:
        raise ApiError("งานนำเข้านี้ต้องใช้ 5 ภาพต่อสถานที่")
    for key in ("max_image_bytes", "max_name_length", "max_description_length"):
        if not isinstance(profile[key], int) or profile[key] <= 0:
            raise ApiError("Profile มีข้อจำกัดขนาดไม่ถูกต้อง")
    return profile


class WebsiteApi:
    def __init__(self, base_url, profile):
        self.base_url = target_url(base_url)
        self.profile = profile
        self.session = requests.Session()
        parsed = urlsplit(self.base_url)
        self.session.headers["Origin"] = f"{parsed.scheme}://{parsed.netloc}"
        self.session.headers["Accept"] = "application/json"

    def close(self):
        self.session.close()

    def _request(self, method, route, **kwargs):
        timeout = kwargs.pop("timeout", (15, 180))
        return self.session.request(method, self.base_url + route, timeout=timeout, allow_redirects=False, **kwargs)

    def login(self, email, password, cookie=""):
        if cookie.strip():
            self.session.headers["Cookie"] = cookie.strip()
        else:
            response = self._request("POST", self.profile["login_path"], json={"email": email.strip(), "password": password})
            if not response.ok or 300 <= response.status_code < 400:
                raise ApiError(f"ล็อกอินไม่สำเร็จ HTTP {response.status_code}")
        return self.check_admin()

    def check_admin(self, timeout=(15, 180)):
        response = self._request("GET", self.profile["session_path"], timeout=timeout)
        if response.status_code == 401:
            raise ApiError("Session หมดอายุ กรุณากดเข้าสู่ระบบผ่านเว็บไซต์อีกครั้ง")
        if response.status_code != 200:
            raise ApiError(f"ตรวจ session ไม่สำเร็จ HTTP {response.status_code}")
        try:
            session = response.json()
            if "data" in session:
                session = session["data"]
            user = session["user"]
            if not isinstance(user, dict):
                raise TypeError("Session user must be an object")
        except (ValueError, TypeError, KeyError) as error:
            raise ApiError("เว็บไซต์ตอบ session ไม่ตรงรูปแบบของ profile") from error
        if user.get("role") != "ADMIN":
            raise ApiError("บัญชีนี้ไม่มีสิทธิ์ ADMIN ของเว็บไซต์ปลายทาง")
        return user.get("email", "Admin")

    def create(self, item):
        fields = self.profile["fields"]
        data = {fields[key]: str(value) for key, value in item["location"].items()}
        try:
            with ExitStack() as stack:
                files = [(fields["images"], (f"image-{index + 1}.webp", stack.enter_context(Path(image["path"]).open("rb")), "image/webp"))
                         for index, image in enumerate(item["images"])]
                response = self._request("POST", self.profile["create_path"], data=data, files=files)
        except requests.RequestException as error:
            raise UncertainUpload("การเชื่อมต่อขาดช่วง กรุณาตรวจสถานที่ในเว็บก่อนอนุญาตให้ส่งซ้ำ") from error
        if response.status_code >= 500 or response.status_code in {408, 409, 425, 429}:
            raise UncertainUpload(f"HTTP {response.status_code} กรุณาตรวจเว็บไซต์ก่อนส่งซ้ำ")
        if response.status_code == 401:
            raise ApiError("Session หมดอายุ กรุณากดเข้าสู่ระบบผ่านเว็บไซต์อีกครั้ง")
        if response.status_code == 403:
            raise ApiError("เว็บไซต์ปฏิเสธสิทธิ์ Admin กรุณาเข้าสู่ระบบด้วยบัญชี Admin ของเว็บไซต์นี้")
        if response.status_code != 201:
            raise ApiError(f"อัปโหลดไม่สำเร็จ HTTP {response.status_code} ตรวจสิทธิ์ ข้อมูล และ profile")
        try:
            location_id = response.json()["data"]["id"]
            if not isinstance(location_id, str) or not location_id:
                raise ValueError("Missing location ID")
            return location_id
        except (ValueError, KeyError, TypeError) as error:
            raise UncertainUpload("เว็บรับคำขอแล้วแต่ตอบ ID ไม่ตรงรูปแบบ กรุณาตรวจเว็บก่อนส่งซ้ำ") from error
