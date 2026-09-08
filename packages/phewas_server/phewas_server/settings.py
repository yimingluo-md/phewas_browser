"""Runtime settings: library home, auth token, where the built frontend lives."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from phewas_core.paths import default_home

ENV_TOKEN = "PHEWAS_TOKEN"
ENV_STATIC = "PHEWAS_STATIC"
ENV_HOME = "PHEWAS_HOME"


def _default_static() -> Path | None:
    env = os.environ.get(ENV_STATIC)
    if env:
        return Path(env)
    # source checkout: <repo>/apps/web/dist ; frozen sidecar: next to the executable
    here = Path(__file__).resolve()
    for base in (here.parents[3] if len(here.parents) > 3 else None, Path.cwd()):
        if base and (base / "apps" / "web" / "dist" / "index.html").exists():
            return base / "apps" / "web" / "dist"
    return None


@dataclass
class Settings:
    home: Path = field(default_factory=default_home)
    token: str = field(default_factory=lambda: os.environ.get(ENV_TOKEN) or secrets.token_urlsafe(32))
    static_dir: Path | None = field(default_factory=_default_static)
    application: str = "PheWAS Browser"

    @classmethod
    def from_env(cls) -> Settings:
        s = cls()
        if os.environ.get(ENV_HOME):
            s.home = Path(os.environ[ENV_HOME]).expanduser()
        return s
