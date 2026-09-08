"""Where the dataset library lives on each platform."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "PheWAS Browser"
ENV_HOME = "PHEWAS_HOME"


def default_home() -> Path:
    """Library root: $PHEWAS_HOME if set, else the platform's per-user app-data folder."""
    env = os.environ.get(ENV_HOME)
    if env:
        return Path(env).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_DIR_NAME
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / "phewas-browser"
