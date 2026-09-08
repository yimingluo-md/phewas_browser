"""FastAPI application: API v1 (dataset-scoped, bearer-token protected) + the built frontend.

GET  /api/health                                   unauthenticated liveness probe
GET  /api/v1/library                               datasets + current
POST /api/v1/library/current        {id}
GET  /api/v1/datasets/{id}                         manifest, cohorts, fields
PATCH/DELETE /api/v1/datasets/{id}                 rename/notes, remove
GET  /api/v1/datasets/{id}/meta                    home page (genes, stats, cohorts, fields)
GET  /api/v1/datasets/{id}/search?q=
GET  /api/v1/datasets/{id}/genes/{gene}
GET  /api/v1/datasets/{id}/variants/{variant}?gene=
GET  /api/v1/profiles, /api/v1/dictionaries
POST /api/v1/import/inspect         {sumstats, annotation?, profile?}
POST /api/v1/import/jobs            {sumstats, annotation?, name, dictionary?, profile?, build?, notes?}
GET  /api/v1/jobs, /api/v1/jobs/{id}, /api/v1/jobs/{id}/events (SSE), POST /api/v1/jobs/{id}/cancel
GET  /api/v1/fs?path=                              directory listing for the file picker
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from phewas_core import __version__ as core_version
from phewas_core.dictionaries import builtin_dictionaries
from phewas_core.importer import ImportRequest, inspect_annotation, inspect_sumstats
from phewas_core.profiles import all_profiles
from phewas_core.query import Dataset, DatasetNotFoundError
from phewas_core.registry import Library
from pydantic import BaseModel, Field

from . import __version__
from .jobs import JobManager
from .settings import Settings

DATA_EXTS = {".tsv", ".txt", ".csv", ".gz", ".bgz", ".zst", ".parquet", ".json"}


# ---------------------------------------------------------------- state


class DatasetCache:
    """Open Dataset objects, one per id, created lazily and closed on removal."""

    def __init__(self, library: Library):
        self.lib = library
        self._open: dict[str, Dataset] = {}
        self._lock = threading.Lock()

    def get(self, dataset_id: str) -> Dataset:
        ref = self.lib.get(dataset_id)  # KeyError -> 404 below
        with self._lock:
            ds = self._open.get(ref.id)
            if ds is None:
                ds = Dataset(ref.db_path)
                self._open[ref.id] = ds
            return ds

    def drop(self, dataset_id: str) -> None:
        with self._lock:
            ds = self._open.pop(dataset_id, None)
        if ds:
            ds.close()

    def refresh_manifest(self, dataset_id: str) -> None:
        self.drop(dataset_id)


class ImportBody(BaseModel):
    sumstats: str
    name: str = ""
    annotation: str | None = None
    dictionary: str = "phecode-1.2"
    profile: str | None = None
    build: str | None = None
    notes: str = "Research Use Only — do not disseminate."
    memory_limit: str | None = None
    make_current: bool = True


class InspectBody(BaseModel):
    sumstats: str | None = None
    annotation: str | None = None
    profile: str | None = None


class DatasetPatch(BaseModel):
    name: str | None = None
    notes: str | None = None


class CurrentBody(BaseModel):
    id: str


class OrderBody(BaseModel):
    ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- app factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    library = Library(settings.home)
    cache = DatasetCache(library)
    jobs = JobManager(library)

    app = FastAPI(title=settings.application, version=__version__, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.library = library
    app.state.cache = cache
    app.state.jobs = jobs

    def require_token(request: Request) -> None:
        auth = request.headers.get("authorization", "")
        token = (
            auth[7:]
            if auth.lower().startswith("bearer ")
            else request.headers.get("x-phewas-token") or request.query_params.get("token")
        )
        if not token or not secrets.compare_digest(token, settings.token):
            raise HTTPException(401, "missing or invalid token")

    def dataset(dataset_id: str) -> Dataset:
        try:
            return cache.get(dataset_id)
        except KeyError as e:
            raise HTTPException(404, str(e)) from None

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "application": settings.application,
            "status": "ok",
            "version": __version__,
            "core": core_version,
        }

    v1 = APIRouter(prefix="/api/v1", dependencies=[Depends(require_token)])

    # ---- library -------------------------------------------------------------
    def library_view() -> dict[str, Any]:
        cur = library.current()
        out = []
        for ref in library.list():
            m = ref.manifest()
            out.append(
                {
                    "id": ref.id,
                    "name": m.name,
                    "created": m.created,
                    "build": m.build,
                    "notes": m.notes,
                    "cohorts": [c.__dict__ for c in m.cohorts],
                    "dictionary": m.dictionary,
                    "stats": m.stats,
                    "warnings": m.warnings,
                    "sources": [s.__dict__ for s in m.sources],
                    "size_bytes": sum(p.stat().st_size for p in ref.dir.iterdir() if p.is_file()),
                }
            )
        return {"datasets": out, "current": cur.id if cur else None, "home": str(library.home)}

    @v1.get("/library")
    def get_library() -> dict[str, Any]:
        return library_view()

    @v1.post("/library/current")
    def set_current(body: CurrentBody) -> dict[str, Any]:
        try:
            library.set_current(body.id)
        except KeyError as e:
            raise HTTPException(404, str(e)) from None
        return library_view()

    @v1.post("/library/order")
    def set_order(body: OrderBody) -> dict[str, Any]:
        library.reorder(body.ids)
        return library_view()

    # ---- datasets ---------------------------------------------------------------
    @v1.get("/datasets/{dataset_id}")
    def get_dataset(dataset_id: str) -> dict[str, Any]:
        ds = dataset(dataset_id)
        ref = library.get(dataset_id)
        m = ds.manifest.to_dict() if ds.manifest else None
        return {
            "id": ref.id,
            "manifest": m,
            "cohorts": ds.cohorts(),
            "fields": ds.fields(),
            "primary_cohort": ds.primary,
            "dir": str(ref.dir),
            "log": (ref.dir / "import.log").read_text(encoding="utf-8")[-20000:]
            if (ref.dir / "import.log").exists()
            else "",
        }

    @v1.patch("/datasets/{dataset_id}")
    def patch_dataset(dataset_id: str, body: DatasetPatch) -> dict[str, Any]:
        try:
            m = library.update_manifest(dataset_id, name=body.name, notes=body.notes)
        except KeyError as e:
            raise HTTPException(404, str(e)) from None
        cache.refresh_manifest(library.get(dataset_id).id)
        return {"id": m.id, "name": m.name, "notes": m.notes}

    @v1.delete("/datasets/{dataset_id}")
    def delete_dataset(dataset_id: str) -> dict[str, Any]:
        try:
            ref = library.get(dataset_id)
        except KeyError as e:
            raise HTTPException(404, str(e)) from None
        cache.drop(ref.id)
        library.remove(ref.id)
        return library_view()

    @v1.get("/datasets/{dataset_id}/meta")
    def get_meta(dataset_id: str) -> dict[str, Any]:
        return dataset(dataset_id).meta()

    @v1.get("/datasets/{dataset_id}/search")
    def search(dataset_id: str, q: str = Query(..., min_length=1)) -> dict[str, Any]:
        return {"results": dataset(dataset_id).search(q)}

    @v1.get("/datasets/{dataset_id}/genes/{gene}")
    def gene_page(dataset_id: str, gene: str) -> dict[str, Any]:
        try:
            return dataset(dataset_id).gene_page(gene)
        except DatasetNotFoundError as e:
            raise HTTPException(404, str(e)) from None

    @v1.get("/datasets/{dataset_id}/variants/{variant_id}")
    def variant_page(dataset_id: str, variant_id: str, gene: str | None = None) -> dict[str, Any]:
        try:
            return dataset(dataset_id).variant_page(variant_id, gene)
        except DatasetNotFoundError as e:
            raise HTTPException(404, str(e)) from None

    # ---- import ------------------------------------------------------------------------
    @v1.get("/profiles")
    def profiles() -> list[dict[str, Any]]:
        return [
            {"name": p.name, "label": p.label, "kind": p.kind, "source": p.source_path}
            for p in all_profiles(library.home)
        ]

    @v1.get("/dictionaries")
    def dictionaries() -> list[dict[str, Any]]:
        return [d.__dict__ for d in builtin_dictionaries()]

    @v1.post("/import/inspect")
    def inspect(body: InspectBody) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if body.sumstats:
            out["sumstats"] = inspect_sumstats(Path(body.sumstats).expanduser(), library.home, body.profile)
        if body.annotation:
            out["annotation"] = inspect_annotation(Path(body.annotation).expanduser())
        return out

    @v1.post("/import/jobs", status_code=202)
    def start_import(body: ImportBody) -> dict[str, Any]:
        sumstats = Path(body.sumstats).expanduser()
        if not sumstats.exists():
            raise HTTPException(400, f"sumstats file not found: {sumstats}")
        annotation = Path(body.annotation).expanduser() if body.annotation else None
        if annotation is not None and not annotation.exists():
            raise HTTPException(400, f"annotation file not found: {annotation}")
        req = ImportRequest(
            sumstats=sumstats,
            name=body.name.strip() or sumstats.name,
            annotation=annotation,
            dictionary=body.dictionary,
            profile=body.profile or None,
            build=body.build,
            notes=body.notes,
            memory_limit=body.memory_limit,
            make_current=body.make_current,
        )
        try:
            job = jobs.start_import(req)
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from None
        return job.snapshot()

    @v1.get("/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        return jobs.list()

    @v1.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        try:
            return jobs.get(job_id).snapshot()
        except KeyError:
            raise HTTPException(404, "no such job") from None

    @v1.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        try:
            return jobs.cancel(job_id).snapshot()
        except KeyError:
            raise HTTPException(404, "no such job") from None

    @v1.get("/jobs/{job_id}/events")
    def job_events(job_id: str, after: int = 0) -> StreamingResponse:
        try:
            job = jobs.get(job_id)
        except KeyError:
            raise HTTPException(404, "no such job") from None

        def gen() -> Iterator[bytes]:
            for e in job.events(after):
                yield f"data: {json.dumps(e)}\n\n".encode()

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---- file picker ------------------------------------------------------------------------
    @v1.get("/fs")
    def fs(path: str | None = None) -> dict[str, Any]:
        roots = [str(Path.home())]
        if sys.platform == "darwin" and Path("/Volumes").is_dir():
            roots.append("/Volumes")
        p = Path(path).expanduser() if path else Path.home()
        if not p.is_dir():
            raise HTTPException(404, f"not a directory: {p}")
        entries = []
        try:
            for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
                if child.name.startswith("."):
                    continue
                try:
                    st = child.stat()
                except OSError:
                    continue
                is_dir = child.is_dir()
                if not is_dir and child.suffix.lower() not in DATA_EXTS:
                    continue
                entries.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "is_dir": is_dir,
                        "size": None if is_dir else st.st_size,
                        "mtime": st.st_mtime,
                    }
                )
        except PermissionError:
            raise HTTPException(403, f"permission denied: {p}") from None
        return {
            "path": str(p),
            "parent": str(p.parent) if p.parent != p else None,
            "roots": roots,
            "entries": entries,
        }

    app.include_router(v1)

    # ---- frontend --------------------------------------------------------------------------------
    static = settings.static_dir
    if static and (static / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(static / "index.html")

        @app.get("/{path:path}")
        def spa(path: str) -> FileResponse:
            f = static / path
            if f.is_file():
                return FileResponse(f)
            return FileResponse(static / "index.html")
    else:

        @app.get("/")
        def no_frontend() -> JSONResponse:
            return JSONResponse(
                {
                    "application": settings.application,
                    "frontend": "not built",
                    "hint": "run `npm run build` in apps/web or set PHEWAS_STATIC",
                }
            )

    return app


def app_from_env() -> FastAPI:
    """Uvicorn entry point: `uvicorn phewas_server.app:app_from_env --factory`."""
    return create_app(Settings.from_env())


__all__ = ["app_from_env", "create_app", "os"]
