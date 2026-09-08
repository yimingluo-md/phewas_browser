"""manifest.json — the self-description of one dataset. Everything the UI needs to know
about cohorts, statistics, annotation fields and provenance lives here, not in code."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import MANIFEST_VERSION, SCHEMA_VERSION

#: Canonical per-association statistics, in display order.
STATISTICS = ("or", "p", "beta", "se", "cases", "case_carriers", "controls", "ctrl_carriers", "aaf", "mac")


@dataclass
class Cohort:
    id: str
    label: str
    is_meta: bool = False
    primary: bool = False


@dataclass
class Source:
    role: str  # "sumstats" | "annotation" | "dictionary"
    path: str
    sha256: str | None = None
    bytes: int | None = None
    rows: int | None = None
    profile: str | None = None


@dataclass
class Manifest:
    id: str
    name: str
    created: str
    app_version: str
    duckdb_version: str
    cohorts: list[Cohort]
    statistics: list[str]
    dictionary: dict[str, str]
    annotation_fields: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    build: str | None = None
    notes: str = ""
    warnings: list[str] = field(default_factory=list)
    manifest_version: int = MANIFEST_VERSION
    schema_version: int = SCHEMA_VERSION

    # ---- convenience -------------------------------------------------
    @property
    def primary_cohort(self) -> Cohort:
        for c in self.cohorts:
            if c.primary:
                return c
        return self.cohorts[0]

    def cohort_ids(self) -> list[str]:
        return [c.id for c in self.cohorts]

    # ---- (de)serialisation --------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(self.dumps(), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Manifest:
        d = dict(d)
        d["cohorts"] = [Cohort(**c) for c in d.get("cohorts", [])]
        d["sources"] = [Source(**s) for s in d.get("sources", [])]
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def load(cls, path: Path) -> Manifest:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
