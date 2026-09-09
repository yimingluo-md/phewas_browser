"""`.phewasds` dataset bundles — one file that moves a dataset between machines.

A bundle is an uncompressed tar (DuckDB files barely compress) holding:

    phewasds.json    format version, dataset id/name, the manifest, file sizes and sha256s
    manifest.json    the dataset's manifest (same content as inside the database)
    dataset.duckdb   the database
    import.log       the original import log (optional)

Import verifies the checksum while extracting, refuses bundles written by a newer schema, keeps
the dataset's original id (so collaborators refer to the same thing), and finalises through the
same atomic rename as a normal import.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import tarfile
import threading
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION, __version__
from .importer import ImportCancelledError, ProgressFn
from .manifest import Manifest
from .registry import DB_FILENAME, MANIFEST_FILENAME, DatasetRef, Library

BUNDLE_FORMAT = 1
BUNDLE_SUFFIX = ".phewasds"
INDEX_NAME = "phewasds.json"
LOG_NAME = "import.log"
CHUNK = 8 * 2**20


class BundleError(ValueError):
    pass


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise ImportCancelledError("cancelled")


class _Progress:
    def __init__(
        self, fn: ProgressFn | None, cancel: threading.Event | None, step: str, total: int, msg: str
    ):
        self.fn, self.cancel, self.step, self.total, self.msg = fn, cancel, step, total, msg
        self.done = 0

    def advance(self, n: int) -> None:
        self.done += n
        _check(self.cancel)
        if self.fn:
            self.fn(self.step, self.done, self.total, self.msg)


class _CountingReader(io.RawIOBase):
    """Wraps a file for tarfile.addfile: reports progress and hashes what passes through."""

    def __init__(self, f: io.BufferedReader, progress: _Progress, h: Any | None = None):
        self.f, self.p, self.h = f, progress, h

    def readable(self) -> bool:
        return True

    def readinto(self, b: bytearray | memoryview) -> int:  # type: ignore[override]
        n = self.f.readinto(b)
        if n:
            if self.h is not None:
                self.h.update(bytes(b[:n]))
            self.p.advance(n)
        return n


def sha256_file(path: Path, progress: ProgressFn | None = None, cancel: threading.Event | None = None) -> str:
    h = hashlib.sha256()
    p = _Progress(progress, cancel, "hash", path.stat().st_size, path.name)
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
            p.advance(len(chunk))
    return h.hexdigest()


# ---------------------------------------------------------------- export


def export_bundle(
    ref: DatasetRef,
    out: Path,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Write `ref` as a bundle to `out` (given a directory, the file is named after the dataset)."""
    out = Path(out).expanduser()
    manifest = ref.manifest()
    if out.is_dir():
        safe = "".join(c if c.isalnum() or c in "-_. " else "_" for c in manifest.name).strip() or ref.id
        out = out / f"{safe}{BUNDLE_SUFFIX}"
    if out.suffix != BUNDLE_SUFFIX:
        out = out.with_name(out.name + BUNDLE_SUFFIX)
    out.parent.mkdir(parents=True, exist_ok=True)
    db = ref.db_path
    size = db.stat().st_size
    digest = sha256_file(db, progress, cancel)
    index = {
        "format": BUNDLE_FORMAT,
        "dataset_id": ref.id,
        "name": manifest.name,
        "schema_version": manifest.schema_version,
        "app_version": __version__,
        "created": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "manifest": manifest.to_dict(),
        "files": {DB_FILENAME: {"bytes": size, "sha256": digest}},
    }
    tmp = out.with_name(out.name + ".partial")
    p = _Progress(progress, cancel, "export", size, out.name)
    try:
        with tarfile.open(tmp, "w", format=tarfile.PAX_FORMAT) as tar:
            for name, payload in (
                (INDEX_NAME, json.dumps(index, indent=2).encode()),
                (MANIFEST_FILENAME, manifest.dumps().encode()),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                info.mtime = int(dt.datetime.now().timestamp())
                tar.addfile(info, io.BytesIO(payload))
            log = ref.dir / LOG_NAME
            if log.exists():
                tar.add(log, arcname=LOG_NAME)
            info = tar.gettarinfo(str(db), arcname=DB_FILENAME)
            with open(db, "rb") as f:
                tar.addfile(info, io.BufferedReader(_CountingReader(f, p)))
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return out


# ---------------------------------------------------------------- inspect / import


def read_index(bundle: Path) -> dict[str, Any]:
    bundle = Path(bundle).expanduser()
    if not bundle.is_file():
        raise BundleError(f"not a file: {bundle}")
    try:
        with tarfile.open(bundle, "r:") as tar:
            member = tar.next()
            if member is None or member.name != INDEX_NAME:
                raise BundleError("not a PheWAS dataset bundle (missing phewasds.json)")
            f = tar.extractfile(member)
            index: dict[str, Any] = json.loads(f.read().decode()) if f else {}
    except tarfile.TarError as e:
        raise BundleError(f"not a PheWAS dataset bundle: {e}") from None
    if index.get("format") != BUNDLE_FORMAT:
        raise BundleError(f"unsupported bundle format {index.get('format')!r}")
    if int(index.get("schema_version", 0)) > SCHEMA_VERSION:
        raise BundleError(
            f"this bundle was written by a newer PheWAS Browser (schema v{index['schema_version']}); update the app"
        )
    return index


def inspect_bundle(bundle: Path, library: Library | None = None) -> dict[str, Any]:
    bundle = Path(bundle).expanduser()
    try:
        index = read_index(bundle)
    except BundleError as e:
        return {"path": str(bundle), "exists": bundle.exists(), "problems": [str(e)]}
    m = index.get("manifest", {})
    problems = []
    if library is not None:
        try:
            existing = library.get(index["dataset_id"])
            problems.append(
                f'this dataset is already in the library as "{existing.manifest().name}" ({existing.id}); remove it first to re-import'
            )
        except KeyError:
            pass
    return {
        "path": str(bundle),
        "exists": True,
        "bytes": bundle.stat().st_size,
        "dataset_id": index["dataset_id"],
        "name": index.get("name"),
        "created": index.get("created"),
        "app_version": index.get("app_version"),
        "cohorts": m.get("cohorts", []),
        "stats": m.get("stats", {}),
        "dictionary": m.get("dictionary"),
        "build": m.get("build"),
        "notes": m.get("notes", ""),
        "warnings": m.get("warnings", []),
        "problems": problems,
    }


def import_bundle(
    library: Library,
    bundle: Path,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
    make_current: bool = True,
    name: str | None = None,
) -> DatasetRef:
    bundle = Path(bundle).expanduser()
    index = read_index(bundle)
    dataset_id = str(index["dataset_id"])
    try:
        library.get(dataset_id)
        raise BundleError(f"dataset {dataset_id} is already in the library; remove it first")
    except KeyError:
        pass
    expected = index["files"][DB_FILENAME]
    partial = library.partial_dir(dataset_id)
    try:
        with tarfile.open(bundle, "r:") as tar:
            members = {m.name: m for m in tar.getmembers()}
            if DB_FILENAME not in members or MANIFEST_FILENAME not in members:
                raise BundleError("bundle is incomplete (dataset.duckdb or manifest.json missing)")
            for plain in (MANIFEST_FILENAME, LOG_NAME):
                if plain in members:
                    f = tar.extractfile(members[plain])
                    if f:
                        (partial / plain).write_bytes(f.read())
            member = members[DB_FILENAME]
            p = _Progress(progress, cancel, "extract", int(expected["bytes"]), bundle.name)
            h = hashlib.sha256()
            src = tar.extractfile(member)
            if src is None:
                raise BundleError("dataset.duckdb is not a regular file in the bundle")
            with open(partial / DB_FILENAME, "wb") as dst:
                while chunk := src.read(CHUNK):
                    h.update(chunk)
                    dst.write(chunk)
                    p.advance(len(chunk))
            if h.hexdigest() != expected["sha256"]:
                raise BundleError("checksum mismatch: the bundle is corrupted or was truncated in transfer")
        manifest = Manifest.load(partial / MANIFEST_FILENAME)
        if name:
            manifest.name = name
        manifest.warnings = [
            *manifest.warnings,
            f"imported from bundle {bundle.name} ({index.get('created', '?')})",
        ]
        manifest.save(partial / MANIFEST_FILENAME)
        _check(cancel)
        return library.finalize(dataset_id, make_current=make_current)
    except BaseException:
        import shutil

        shutil.rmtree(partial, ignore_errors=True)
        raise
