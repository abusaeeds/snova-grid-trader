"""Paths and saved preferences.

Only the login number, server name and terminal path are remembered.
The password is never written to disk.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SETTINGS_DIR = Path.home() / ".snova_grid_trader"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"


def resource_path(relative: str) -> str:
    """Absolute path to a bundled file. Works in source and in a PyInstaller .exe."""
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)
    return os.path.join(base, relative)


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    safe = {k: v for k, v in data.items() if k != "password"}
    try:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(safe, indent=2), encoding="utf-8")
    except OSError:
        pass
