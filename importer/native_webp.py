"""Official cwebp encoder with native size targeting and cancellable child processes."""
import os
from pathlib import Path
import subprocess

ENCODER = Path(__file__).resolve().parents[1] / "tools/webp/cwebp.exe"


class NativeEncodingError(Exception):
    pass


def native_available():
    return os.name == "nt" and ENCODER.is_file()


def run_encoder(arguments, cancel):
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
    try:
        with subprocess.Popen([str(ENCODER), *arguments], stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, creationflags=flags) as process:
            while process.poll() is None:
                if cancel.wait(0.05):
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise ValueError("หยุดการเตรียมข้อมูลแล้ว")
            error = process.stderr.read().decode("utf-8", errors="replace")
            if process.returncode:
                raise NativeEncodingError(error[-300:] or f"cwebp exit {process.returncode}")
    except OSError as error:
        raise NativeEncodingError(str(error)) from error


def native_fit(image, output, max_bytes, prefer_lossless, cancel, progress):
    raw = output.with_name(output.name + ".input.png")
    temporary = output.with_name(output.name + ".native.webp")
    try:
        if cancel.is_set():
            raise ValueError("หยุดการเตรียมข้อมูลแล้ว")
        # Store oriented full-resolution pixels without spending CPU on PNG compression.
        image.save(raw, format="PNG", compress_level=0)
        common = ["-quiet", "-mt", "-m", "4", "-metadata", "none", "-exact"]
        if prefer_lossless:
            progress("native · ลอง lossless แบบเร็ว")
            run_encoder([*common, "-lossless", "-q", "75", str(raw), "-o", str(temporary)], cancel)
            if temporary.stat().st_size <= max_bytes:
                temporary.replace(output)
                return None, True
        target = max_bytes - max(1024, max_bytes // 500)
        for attempt in range(3):
            progress(f"native · กำหนดขนาดเป้าหมาย {target / 1048576:.2f} MiB")
            run_encoder([*common, "-q", "100", "-qrange", "1", "100", "-size", str(target),
                         "-pass", "6", str(raw), "-o", str(temporary)], cancel)
            if temporary.stat().st_size <= max_bytes:
                temporary.replace(output)
                # cwebp's target-size optimizer chooses quality internally.
                return None, False
            target = int(target * 0.97)
        raise NativeEncodingError("ผล native เกินขนาด API หลังตรวจซ้ำ")
    finally:
        raw.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
