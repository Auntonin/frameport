"""Native WebP encoding and resumable per-image cache."""
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, features, __version__ as pillow_version

from .files import atomic_json, file_hash
from .native_webp import NativeEncodingError, native_available, native_fit

ENCODER_METHOD = 4

WEBP_MAX_QUALITY = 100



def fit_webp(image, output, max_bytes, prefer_lossless, cancel, progress):
    if native_available() and isinstance(image, Image.Image) and max_bytes >= 4096:
        try:
            return native_fit(image, output, max_bytes, prefer_lossless, cancel, progress)
        except NativeEncodingError as error:
            progress(f"ใช้ตัวแปลงสำรอง Pillow · {error}")
    temporary = output.with_suffix(".tmp")

    def encode(quality, lossless):
        if cancel.is_set():
            temporary.unlink(missing_ok=True)
            raise ValueError("หยุดการเตรียมข้อมูลแล้ว")
        progress("กำลังลอง lossless" if lossless else f"กำลังตรวจคุณภาพ {quality}")
        # In lossless mode quality controls compression effort, not pixel fidelity.
        encoding_quality = 95 if lossless else quality
        image.save(temporary, format="WEBP", quality=encoding_quality, method=ENCODER_METHOD, lossless=lossless, exact=lossless)
        return temporary.stat().st_size

    if prefer_lossless and encode(WEBP_MAX_QUALITY, True) <= max_bytes:
        temporary.replace(output)
        return None, True
    if encode(WEBP_MAX_QUALITY, False) <= max_bytes:
        temporary.replace(output)
        return WEBP_MAX_QUALITY, False
    low, high = 1, WEBP_MAX_QUALITY - 1
    best = None
    while low <= high:
        quality = (low + high) // 2
        if encode(quality, False) <= max_bytes:
            temporary.replace(output)
            best = quality
            low = quality + 1
        else:
            high = quality - 1
    temporary.unlink(missing_ok=True)
    if best is None:
        raise ValueError(f"ภาพยังเกินข้อจำกัด API {max_bytes / 1048576:.2f} MiB แม้ใช้คุณภาพต่ำสุดที่ความละเอียดเดิม")
    return best, False



def cached_image(output, source_hash, max_bytes):
    receipt = output.with_suffix(".json")
    try:
        record = json.loads(receipt.read_text(encoding="utf-8"))
        image = record["image"]
        if record["source_sha256"] != source_hash or output.stat().st_size > max_bytes:
            return None
        if output.stat().st_size != image["bytes"] or file_hash(output) != image["sha256"]:
            return None
        with Image.open(output) as converted:
            if converted.format != "WEBP" or converted.size != (image["width"], image["height"]):
                return None
        return {**image, "path": str(output.resolve())}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def location_identity(location, profile, lossless):
    hashes = [file_hash(path) for path in location.files]
    identity = {"location": location.payload(), "sources": hashes, "lossless": lossless,
                "quality": WEBP_MAX_QUALITY, "pillow": pillow_version, "webp": features.version("webp"),
                "format": 2, "lossless_effort": 95, "max_image_bytes": profile["max_image_bytes"]}
    fingerprint = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    settings = {key: value for key, value in identity.items() if key not in {"location", "sources"}}
    settings["method"] = ENCODER_METHOD
    cache_keys = [sha256(json.dumps({**settings, "source": digest}, sort_keys=True).encode()).hexdigest() for digest in hashes]
    return {"hashes": hashes, "fingerprint": fingerprint, "cache_keys": cache_keys}


def convert_image(path, index, identity, cache, profile, lossless, cancel, progress, lock):
    with lock:
        if cancel.is_set():
            raise ValueError("หยุดการเตรียมข้อมูลแล้ว")
        source_hash = identity["hashes"][index]
        with Image.open(path) as original:
            if original.format == "WEBP" and getattr(original, "n_frames", 1) == 1 and path.stat().st_size <= profile["max_image_bytes"]:
                width, height = original.size
                original.verify()
                if file_hash(path) != source_hash:
                    raise ValueError(f"ต้นฉบับเปลี่ยนระหว่างตรวจ {path.name}")
                progress(f"ใช้ WebP ที่พร้อมแล้ว · {path.name}")
                return {"path": str(path.resolve()), "sha256": source_hash, "bytes": path.stat().st_size,
                        "source": path.name, "width": width, "height": height, "quality": None,
                        "lossless": None, "over_limit": False, "passthrough": True}, 1
        output = cache / f"{identity['cache_keys'][index]}.webp"
        image = cached_image(output, source_hash, profile["max_image_bytes"])
        if image is not None:
            if file_hash(path) != source_hash:
                raise ValueError(f"ต้นฉบับเปลี่ยนระหว่างแปลง {path.name}")
            progress(f"ใช้ไฟล์ที่แปลงแล้ว · {path.name}")
            return {**image, "source": path.name}, 1
        work = cache / f"{identity['cache_keys'][index]}-{uuid4().hex[:8]}.webp"
        try:
            with Image.open(path) as original:
                if original.format == "MPO":
                    original.seek(0)
                elif getattr(original, "n_frames", 1) != 1:
                    raise ValueError(f"ภาพเคลื่อนไหวใช้ไม่ได้ {path.name}")
                with ImageOps.exif_transpose(original) as oriented:
                    has_alpha = oriented.mode in {"RGBA", "LA"} or "transparency" in oriented.info
                    with oriented.convert("RGBA" if has_alpha else "RGB") as pixels:
                        quality, encoded_lossless = fit_webp(
                            pixels, work, profile["max_image_bytes"], lossless, cancel,
                            lambda status: progress(f"{path.name} · {status}"),
                        )
                        width, height = pixels.size
            if file_hash(path) != source_hash:
                raise ValueError(f"ต้นฉบับเปลี่ยนระหว่างแปลง {path.name}")
            work.replace(output)
            image = {"path": str(output.resolve()), "sha256": file_hash(output), "bytes": output.stat().st_size,
                     "source": path.name, "width": width, "height": height, "quality": quality,
                     "lossless": encoded_lossless, "over_limit": False}
            atomic_json(output.with_suffix(".json"), {"source_sha256": source_hash, "image": image})
            return image, 0
        finally:
            work.unlink(missing_ok=True)
            work.with_suffix(".tmp").unlink(missing_ok=True)
