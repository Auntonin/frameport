"""Durable, target-specific progress with explicit handling of uncertain requests."""
import json
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import sqlite3

from .api import ApiError
from .plan import file_hash


class Journal:
    def __init__(self, path):
        self.path = path
        with self.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS uploads (
                target TEXT NOT NULL, fingerprint TEXT NOT NULL, state TEXT NOT NULL,
                location_id TEXT, name TEXT NOT NULL, PRIMARY KEY(target, fingerprint))""")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def state(self, target, fingerprint):
        with self.connect() as connection:
            row = connection.execute("SELECT state, location_id FROM uploads WHERE target=? AND fingerprint=?", (target, fingerprint)).fetchone()
            return row or ("ready", None)

    def reserve(self, target, item):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT state FROM uploads WHERE target=? AND fingerprint=?", (target, item["fingerprint"])).fetchone()
            if row and row[0] == "done":
                return False
            if row and row[0] == "pending":
                raise ApiError(f"{item['location']['name']} มีคำขอค้าง กรุณาตรวจเว็บไซต์ก่อนอนุญาตให้ส่งซ้ำ")
            connection.execute("INSERT OR REPLACE INTO uploads VALUES (?, ?, 'pending', NULL, ?)", (target, item["fingerprint"], item["location"]["name"]))
        return True

    def finish(self, target, fingerprint, state, location_id=None):
        with self.connect() as connection:
            connection.execute("UPDATE uploads SET state=?, location_id=? WHERE target=? AND fingerprint=?", (state, location_id, target, fingerprint))

    def allow_retry(self, target, fingerprint):
        with self.connect() as connection:
            connection.execute("UPDATE uploads SET state='retry' WHERE target=? AND fingerprint=? AND state='pending'", (target, fingerprint))


def destination_key(api):
    # Bind receipts to both the destination and the exact API contract.
    return api.base_url + "#" + sha256(json.dumps({key: value for key, value in api.profile.items() if key != "login_page"}, sort_keys=True).encode()).hexdigest()


def upload_all(api, items, journal, cancel, progress):
    target = destination_key(api)
    # Validate all cached files before the first remote write.
    for item in items:
        for image in item["images"]:
            if Path(image["path"]).stat().st_size > api.profile["max_image_bytes"]:
                raise ApiError(f"{image['source']} เกินข้อจำกัด API {api.profile['max_image_bytes'] / 1048576:.2f} MiB ต้องเพิ่มขนาดที่เว็บไซต์รับก่อนนำเข้า")
            if file_hash(Path(image["path"])) != image["sha256"]:
                raise ApiError("ไฟล์ WebP เปลี่ยนหลัง preview กรุณาเตรียมข้อมูลใหม่")
    for index, item in enumerate(items):
        if cancel.is_set():
            progress("หยุดแล้ว รายการที่สำเร็จเก็บประวัติไว้ สามารถเริ่มต่อได้")
            return
        for image in item["images"]:
            if file_hash(Path(image["path"])) != image["sha256"]:
                raise ApiError("ไฟล์ภาพเปลี่ยนระหว่างนำเข้า กรุณากดเริ่มนำเข้าใหม่เพื่อตรวจไฟล์ปัจจุบัน")
        if not journal.reserve(target, item):
            progress(f"{index + 1}/{len(items)} ข้ามรายการที่สำเร็จแล้ว · {item['location']['name']}")
            continue
        try:
            location_id = api.create(item)
        except ApiError as error:
            from .api import UncertainUpload
            if not isinstance(error, UncertainUpload):
                journal.finish(target, item["fingerprint"], "failed")
            raise
        journal.finish(target, item["fingerprint"], "done", location_id)
        progress(f"{index + 1}/{len(items)} สำเร็จ · {item['location']['name']} · ID {location_id}")
    progress("นำเข้าครบแล้ว")
