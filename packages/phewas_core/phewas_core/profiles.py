"""Import profiles: JSON documents that map one sumstats file layout onto the canonical schema.

Two layouts are supported by the profile *kind*, inferred from the keys present:
  * wide  — one row per (variant, trait); per-cohort statistics live in columns whose
            names match `cohort_columns.pattern` (named groups `stat` and `cohort`), and
            the meta-analysis lives in `meta_columns.map`.
  * long  — one row per (variant, trait, cohort); statistics in `stat_columns`.

Built-in profiles ship in builtin/profiles/. User profiles live in <home>/profiles/.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from .manifest import STATISTICS


class ProfileError(ValueError):
    pass


@dataclass
class CohortSpec:
    id: str
    label: str
    is_meta: bool
    columns: dict[str, str]  # canonical stat -> source column


@dataclass
class Profile:
    name: str
    label: str
    keys: dict[str, str]
    delimiter: str = "\t"
    nulls: list[str] = field(default_factory=lambda: ["NA", ""])
    variant_columns: dict[str, str] = field(default_factory=dict)
    variant_id_format: str = "chr:pos:ref:alt"
    strip_chr_prefix: bool = True
    cohort_pattern: str | None = None
    stat_map: dict[str, str] = field(default_factory=dict)
    meta_cohort_id: str | None = None
    meta_label: str = "Meta-analysis"
    meta_map: dict[str, str] = field(default_factory=dict)
    cohort_labels: dict[str, str] = field(default_factory=dict)
    stat_columns: dict[str, str] = field(default_factory=dict)
    meta_cohort_ids: list[str] = field(default_factory=lambda: ["META"])
    trait_filter: str = "in_dictionary"
    required_columns: list[str] = field(default_factory=list)
    source_path: str | None = None

    @property
    def kind(self) -> str:
        return "long" if "cohort" in self.keys else "wide"

    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, d: dict[str, Any], source_path: str | None = None) -> Profile:
        if d.get("profile_version", 1) != 1:
            raise ProfileError(f"unsupported profile_version {d.get('profile_version')}")
        fmt = d.get("format", {})
        cc = d.get("cohort_columns", {})
        mc = d.get("meta_columns", {})
        p = cls(
            name=d["name"],
            label=d.get("label", d["name"]),
            keys=d["keys"],
            delimiter=fmt.get("delimiter", "\t"),
            nulls=fmt.get("null", ["NA", ""]),
            variant_columns=d.get("variant_columns", {}),
            variant_id_format=d.get("variant_id_format", "chr:pos:ref:alt"),
            strip_chr_prefix=d.get("strip_chr_prefix", True),
            cohort_pattern=cc.get("pattern"),
            stat_map=cc.get("stat_map", {}),
            meta_cohort_id=mc.get("cohort_id"),
            meta_label=mc.get("label", "Meta-analysis"),
            meta_map=mc.get("map", {}),
            cohort_labels=d.get("cohort_labels", {}),
            stat_columns=d.get("stat_columns", {}),
            meta_cohort_ids=d.get("meta_cohort_ids", ["META"]),
            trait_filter=d.get("trait_filter", "in_dictionary"),
            required_columns=d.get("required_columns", []),
            source_path=source_path,
        )
        for k in ("variant_id", "gene", "trait"):
            if k not in p.keys:
                raise ProfileError(f"profile {p.name}: keys.{k} is required")
        bad = [
            s
            for s in list(p.stat_map.values()) + list(p.meta_map.values()) + list(p.stat_columns)
            if s not in STATISTICS
        ]
        if bad:
            raise ProfileError(f"profile {p.name}: unknown statistics {bad}; allowed: {STATISTICS}")
        return p

    @classmethod
    def load(cls, path: Path) -> Profile:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")), str(path))

    # ------------------------------------------------------------------
    def missing_columns(self, header: list[str]) -> list[str]:
        want = list(self.keys.values()) + list(self.required_columns)
        return [c for c in want if c not in header]

    def cohorts_for_header(self, header: list[str]) -> list[CohortSpec]:
        """Resolve which cohorts (and which of their stat columns) exist in this file.
        Order: meta first, then cohorts in order of first appearance in the header."""
        cols = set(header)
        if self.kind == "long":
            # cohorts are values, not columns — resolved at import time from the data
            return []
        specs: list[CohortSpec] = []
        if self.meta_cohort_id:
            m = {stat: col for col, stat in self.meta_map.items() if col in cols}
            if m:
                specs.append(CohortSpec(self.meta_cohort_id, self.meta_label, True, m))
        if self.cohort_pattern:
            rx = re.compile(self.cohort_pattern)
            found: dict[str, dict[str, str]] = {}
            claimed = set(self.meta_map)  # e.g. Beta_Meta must not become cohort "Meta"
            for c in header:
                if c in claimed:
                    continue
                mt = rx.match(c)
                if not mt or (
                    self.meta_cohort_id and mt.group("cohort").lower() == self.meta_cohort_id.lower()
                ):
                    continue
                stat = self.stat_map.get(mt.group("stat"))
                if stat is None:
                    continue
                found.setdefault(mt.group("cohort"), {})[stat] = c
            for cid, m in found.items():
                if "p" in m or "or" in m or "beta" in m:
                    specs.append(CohortSpec(cid, self.cohort_labels.get(cid, cid), False, m))
        if not specs:
            raise ProfileError(f"profile {self.name}: no cohort statistics found in header")
        return specs


# ---------------------------------------------------------------- discovery


def builtin_profiles() -> list[Profile]:
    out = []
    for entry in sorted(resources.files("phewas_core.builtin.profiles").iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".json"):
            out.append(
                Profile.from_dict(json.loads(entry.read_text(encoding="utf-8")), f"builtin:{entry.name}")
            )
    return out


def user_profiles(home: Path) -> list[Profile]:
    d = Path(home) / "profiles"
    return [Profile.load(p) for p in sorted(d.glob("*.json"))] if d.is_dir() else []


def all_profiles(home: Path | None = None) -> list[Profile]:
    profs = builtin_profiles()
    if home is not None:
        profs += user_profiles(home)
    return profs


def get_profile(name_or_path: str, home: Path | None = None) -> Profile:
    p = Path(name_or_path)
    if p.suffix == ".json" and p.exists():
        return Profile.load(p)
    for prof in all_profiles(home):
        if prof.name == name_or_path:
            return prof
    raise ProfileError(f"unknown profile {name_or_path!r}; available: {[q.name for q in all_profiles(home)]}")


def match_profile(header: list[str], home: Path | None = None) -> Profile | None:
    """Best built-in/user profile for a header: all keys and required columns present,
    and (for wide) at least one cohort resolved. Ties broken by the number of matched columns."""
    best: tuple[int, Profile] | None = None
    for prof in all_profiles(home):
        if prof.missing_columns(header):
            continue
        try:
            n = (
                sum(len(c.columns) for c in prof.cohorts_for_header(header))
                if prof.kind == "wide"
                else sum(1 for c in prof.stat_columns.values() if c in header)
            )
        except ProfileError:
            continue
        if best is None or n > best[0]:
            best = (n, prof)
    return best[1] if best else None
