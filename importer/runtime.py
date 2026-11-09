"""Bundled resources, per-user state, and preservation of existing import receipts."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys

from .files import atomic_json

VERSION = "1.0.0"
ASSETS = Path(__file__).resolve().parents[1]
APP_DIRECTORY = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else ASSETS


def data_directory():
    override = os.environ.get("FRAMEPORT_DATA_DIR")
    if override:
        return Path(override).resolve()
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share")))
    return base / "FramePort"


def initialize_data(directory, legacy_candidates):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "history.sqlite3"
    if target.exists() or os.environ.get("FRAMEPORT_DATA_DIR"):
        return
    for legacy in legacy_candidates:
        source = legacy / "history.sqlite3"
        if source.is_file() and source.resolve() != target.resolve():
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as old:
                with closing(sqlite3.connect(target)) as new:
                    old.backup(new)
            return


def read_preferences(directory):
    path = directory / "preferences.json"
    if not path.exists():
        return {}
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Invalid preferences")
    for key in ("url", "excel", "images", "custom_profile"):
        if key in result and not isinstance(result[key], str):
            raise ValueError("Invalid preferences")
    for key in ("header", "lossless"):
        if key in result and not isinstance(result[key], bool):
            raise ValueError("Invalid preferences")
    return result


def save_preferences(directory, preferences):
    allowed = {key: value for key, value in preferences.items() if key in {"url", "excel", "images", "header", "lossless", "custom_profile"}}
    atomic_json(directory / "preferences.json", allowed)
