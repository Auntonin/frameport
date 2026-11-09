"""Choose native encoder concurrency from currently available CPU and RAM."""
import ctypes
import os

from .native_webp import native_available


def available_memory():
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
                (name, ctypes.c_uint64) for name in (
                    "total", "available", "page_total", "page_available",
                    "virtual_total", "virtual_available", "extended_available",
                )
            ]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.total, status.available
    return None


def choose_workers(job_count, max_pixels, requested=None):
    threads_per_image = 2 if native_available() else 1
    cpu_limit = max(1, ((os.cpu_count() or 2) - 1) // threads_per_image)
    limit = min(max(1, job_count), cpu_limit)
    memory = available_memory()
    if memory:
        total, available = memory
        reserve = max(1024 ** 3, int(total * 0.08))
        # Decoded pixels, encoder analysis buffers, and working/output copies.
        bytes_per_pixel = 32 if threads_per_image == 2 else 24
        per_worker = max_pixels * bytes_per_pixel + 128 * 1024 ** 2
        memory_limit = max(1, (available - reserve) // per_worker)
        limit = min(limit, memory_limit)
    if requested is not None:
        if requested < 1:
            raise ValueError("workers must be positive")
        limit = min(limit, requested)
    return max(1, limit)


def initialize_worker():
    if os.name == "nt":
        # Use spare CPU fully while allowing the UI and other apps to preempt us.
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentThread.restype = ctypes.c_void_p
        kernel.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
        kernel.SetThreadPriority(kernel.GetCurrentThread(), -1)
