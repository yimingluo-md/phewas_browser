"""The dataset library: <home>/registry.json plus one directory per dataset.

    <home>/
      registry.json                 {"datasets": [ids in display order], "current": id}
      datasets/<id>/manifest.json
      datasets/<id>/dataset.duckdb
      datasets/<id>/import.log
      profiles/*.json               user import profiles

Datasets are immutable once finalised; an import writes into datasets/<id>.partial/
and renames it into place, so a crash can never leave a half-built dataset visible.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .manifest import Manifest
from .paths import default_home

DB_FILENAME = "dataset.duckdb"
MANIFEST_FILENAME = "manifest.json"


@dataclass(frozen=True)
class DatasetRef:
    id: str
    dir: Path

    @property
    def db_path(self) -> Path:
        return self.dir / DB_FILENAME

    @property
    def manifest_path(self) -> Path:
        return self.dir / MANIFEST_FILENAME

    def manifest(self) -> Manifest:
        return Manifest.load(self.manifest_path)


class Library:
    def __init__(self, home: Path | None = None):
        self.home = Path(home) if home else default_home()
        self.datasets_dir = self.home / "datasets"
        self.registry_path = self.home / "registry.json"

    # ---- registry file -------------------------------------------------
    def _read(self) -> dict[str, Any]:
        if self.registry_path.exists():
            data: dict[str, Any] = json.loads(self.registry_path.read_text(encoding="utf-8"))
            return data
        return {"datasets": [], "current": None}

    def _write(self, reg: dict[str, Any]) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = self.registry_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.registry_path)

    # ---- queries --------------------------------------------------------
    def list(self) -> list[DatasetRef]:
        reg = self._read()
        refs = []
        for did in reg["datasets"]:
            d = self.datasets_dir / did
            if (d / MANIFEST_FILENAME).exists() and (d / DB_FILENAME).exists():
                refs.append(DatasetRef(did, d))
        return refs

    def get(self, id_or_prefix: str) -> DatasetRef:
        p = Path(id_or_prefix)
        if p.is_dir() and (p / MANIFEST_FILENAME).exists():
            return DatasetRef(p.name, p)
        hits = [r for r in self.list() if r.id == id_or_prefix or r.id.startswith(id_or_prefix)]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise KeyError(f"no dataset {id_or_prefix!r} in {self.home}")
        raise KeyError(f"ambiguous dataset id {id_or_prefix!r}: {[h.id for h in hits]}")

    def current(self) -> DatasetRef | None:
        reg = self._read()
        if reg.get("current"):
            try:
                return self.get(reg["current"])
            except KeyError:
                pass
        refs = self.list()
        return refs[0] if refs else None

    def set_current(self, dataset_id: str) -> None:
        reg = self._read()
        reg["current"] = self.get(dataset_id).id
        self._write(reg)

    # ---- lifecycle ------------------------------------------------------
    def new_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def partial_dir(self, dataset_id: str) -> Path:
        d = self.datasets_dir / f"{dataset_id}.partial"
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        return d

    def finalize(self, dataset_id: str, make_current: bool = True) -> DatasetRef:
        """Atomically move datasets/<id>.partial into place and register it."""
        partial = self.datasets_dir / f"{dataset_id}.partial"
        final = self.datasets_dir / dataset_id
        if not (partial / MANIFEST_FILENAME).exists():
            raise FileNotFoundError(f"{partial} has no manifest; import did not finish")
        partial.rename(final)
        reg = self._read()
        if dataset_id not in reg["datasets"]:
            reg["datasets"].append(dataset_id)
        if make_current or not reg.get("current"):
            reg["current"] = dataset_id
        self._write(reg)
        return DatasetRef(dataset_id, final)

    def remove(self, id_or_prefix: str) -> None:
        ref = self.get(id_or_prefix)
        shutil.rmtree(ref.dir)
        reg = self._read()
        reg["datasets"] = [d for d in reg["datasets"] if d != ref.id]
        if reg.get("current") == ref.id:
            reg["current"] = reg["datasets"][0] if reg["datasets"] else None
        self._write(reg)
