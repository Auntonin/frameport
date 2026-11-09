"""Local Excel planning and full-resolution WebP preparation, independent of the website."""
from dataclasses import dataclass
from contextlib import ExitStack
import csv
import math
from pathlib import Path
import re
from threading import Event, Lock

from openpyxl import load_workbook
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter

from .conversion import convert_image, location_identity, fit_webp
from .exports import export_prepared
from .files import atomic_json, cache_job_lock, file_hash
from .resources import choose_workers, initialize_worker


@dataclass
class Location:
    row: int
    name: str
    description: str
    latitude: float
    longitude: float
    files: list[Path]

    def payload(self):
        return {key: getattr(self, key) for key in ("name", "description", "latitude", "longitude")}


def natural_key(path):
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r"(\d+)", path.name))


def read_plan(excel: Path, directory: Path, profile: dict, header=True):
    count = profile["images_per_location"]
    files = sorted((path for path in directory.iterdir()
                    if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}), key=natural_key)
    if len({natural_key(path) for path in files}) != len(files):
        raise ValueError("ชื่อภาพเรียงลำดับกำกวม เช่น IMG_1 กับ IMG_01 กรุณาเปลี่ยนชื่อก่อน")
    locations = []
    with ExitStack() as stack:
        if excel.suffix.lower() == ".csv":
            stream = stack.enter_context(excel.open(encoding="utf-8-sig", newline=""))
            rows = ((number, (values + [None] * 4)[:4], False) for number, values in enumerate(csv.reader(stream), 1))
        else:
            workbook = load_workbook(excel, read_only=True, data_only=False)
            stack.callback(workbook.close)
            if len(workbook.worksheets) != 1:
                raise ValueError("Excel ต้องมีหนึ่ง worksheet")
            rows = ((number, [cell.value for cell in cells], any(cell.data_type == "f" for cell in cells[1:]))
                    for number, cells in enumerate(workbook.worksheets[0].iter_rows(max_col=4), 1))
        for number, values, formula in rows:
            if header and number == 1:
                continue
            if all(value is None or str(value).strip() == "" for value in values[1:]):
                continue
            if formula:
                raise ValueError(f"แถว {number} ต้องใช้ข้อความธรรมดาใน B–D แทนสูตร")
            coordinate = str(values[1] or "").split(",")
            if len(coordinate) != 2 or any(not re.fullmatch(r"-?\d+(?:\.\d+)?", part.strip()) for part in coordinate):
                raise ValueError(f"แถว {number} พิกัดต้องเป็น latitude,longitude")
            latitude, longitude = map(float, coordinate)
            if not (math.isfinite(latitude) and -90 <= latitude <= 90 and math.isfinite(longitude) and -180 <= longitude <= 180):
                raise ValueError(f"แถว {number} พิกัดอยู่นอกช่วง")
            name = str(values[2] or "").strip()
            description = str(values[3] or "").strip()
            if not name or len(name) > profile["max_name_length"] or len(description) > profile["max_description_length"]:
                raise ValueError(f"แถว {number} ตรวจชื่อและความยาวรายละเอียด")
            start = len(locations) * count
            locations.append(Location(number, name, description, latitude, longitude, files[start:start + count]))
    if not locations or len(files) != len(locations) * count:
        raise ValueError(f"พบ {len(locations)} สถานที่ ต้องมี {len(locations) * count} ภาพ แต่พบ {len(files)} ภาพ")
    return locations


def prepare(plan, cache: Path, profile: dict, lossless: bool, cancel: Event, progress, *, workers=None, export_directory=None, export_files=True):
    started = perf_counter()
    if cancel.is_set():
        raise ValueError("หยุดการเตรียมข้อมูลแล้ว")
    cache.mkdir(parents=True, exist_ok=True)
    with cache_job_lock(cache):
        max_pixels = 0
        for item in plan:
            for path in item.files:
                with Image.open(path) as image:
                    max_pixels = max(max_pixels, image.width * image.height)
        progress("กำลังตรวจข้อมูลต้นฉบับและ cache…")
        identities = [location_identity(item, profile, lossless) for item in plan]
        jobs = [(location_index, image_index) for location_index, item in enumerate(plan)
                for image_index in range(len(item.files))]
        count = choose_workers(len(jobs), max_pixels, workers)
        progress(f"แปลงพร้อมกัน {count} ภาพ · ปรับตาม CPU และแรมว่าง")
        prepared = [{"row": item.row, "location": item.payload(), "fingerprint": identity["fingerprint"],
                     "images": [None] * len(item.files)} for item, identity in zip(plan, identities)]
        hits = 0
        cache_locks = {}
        with ThreadPoolExecutor(max_workers=count, initializer=initialize_worker) as pool:
            futures = {pool.submit(convert_image, plan[row].files[number], number, identities[row], cache,
                                   profile, lossless, cancel, progress, cache_locks.setdefault(identities[row]["cache_keys"][number], Lock())): (row, number) for row, number in jobs}
            try:
                for completed, future in enumerate(as_completed(futures), 1):
                    row, number = futures[future]
                    prepared[row]["images"][number], cached = future.result()
                    hits += cached
                    progress(f"สำเร็จ {completed}/{len(jobs)} ภาพ · {plan[row].files[number].name}")
            except BaseException:
                cancel.set()
                for future in futures:
                    future.cancel()
                raise
        if export_files:
            exported, directory = export_prepared(prepared, export_directory or cache.parent / "ready-to-upload", cancel)
        else:
            exported, directory = prepared, None
        atomic_json(cache.parent / "preview.json", exported)
        atomic_json(cache.parent / "performance.json", {
            "workers": count, "locations": len(plan), "images": len(jobs), "cache_hits": hits,
            "elapsed_seconds": round(perf_counter() - started, 3),
            "export_directory": str(directory.resolve()) if directory is not None else None, "encoder_method": 4,
        })
        progress(f"ตรวจภาพพร้อมนำเข้า {len(jobs)} ภาพ · ใช้ไฟล์ที่พร้อมแล้ว {hits} ภาพ")
        return exported
