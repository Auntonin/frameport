"""Readable five-photo folders containing the exact files used for API uploads."""
from hashlib import sha256
import json
from pathlib import Path
import re

from .files import atomic_json, export_file


def safe_name(value, limit):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")[:limit] or "location"


def export_prepared(items, directory, cancel):
    identity = [(item["fingerprint"], [image["sha256"] for image in item["images"]]) for item in items]
    batch = sha256(json.dumps(identity).encode()).hexdigest()[:16]
    destination = Path(directory) / batch
    destination.mkdir(parents=True, exist_ok=True)
    exported = []
    for index, item in enumerate(items):
        folder = destination / f"{index + 1:04d}-{safe_name(item['location']['name'], 48)}"
        images = []
        for number, image in enumerate(item["images"], 1):
            if cancel.is_set():
                raise ValueError("หยุดการเตรียมข้อมูลแล้ว")
            filename = f"{number:02d}-{safe_name(Path(image['source']).stem, 64)}.webp"
            output = folder / filename
            export_file(image["path"], output)
            images.append({**image, "path": str(output.resolve())})
        exported.append({**item, "images": images})
    atomic_json(destination / "manifest.json", exported)
    return exported, destination
