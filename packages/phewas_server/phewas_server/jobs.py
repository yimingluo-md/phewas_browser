"""Background import jobs with progress events (polled or streamed as SSE)."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from phewas_core.bundle import export_bundle, import_bundle
from phewas_core.importer import ImportCancelledError, ImportRequest, ProgressFn, run_import
from phewas_core.registry import Library


@dataclass
class Job:
    id: str
    kind: str
    request: dict[str, Any]
    status: str = "queued"  # queued | running | done | failed | cancelled
    step: str = ""
    done: int = 0
    total: int = 0
    message: str = ""
    error: str | None = None
    result: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    seq: int = 0
    cancel: threading.Event = field(default_factory=threading.Event)
    _cond: threading.Condition = field(default_factory=threading.Condition)
    _events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=2000))

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "step": self.step,
            "done": self.done,
            "total": self.total,
            "message": self.message,
            "error": self.error,
            "result": self.result,
            "warnings": self.warnings,
            "created": self.created,
            "started": self.started,
            "finished": self.finished,
            "seq": self.seq,
            "request": {k: v for k, v in self.request.items()},
        }

    def _emit(self, **changes: Any) -> None:
        with self._cond:
            for k, v in changes.items():
                setattr(self, k, v)
            self.seq += 1
            self._events.append(self.snapshot())
            self._cond.notify_all()

    def events(self, after_seq: int = 0, timeout: float = 15.0) -> Iterator[dict[str, Any]]:
        """Yield snapshots newer than `after_seq`; blocks up to `timeout` for the next one.
        Stops once the job has finished and everything was delivered."""
        last = after_seq
        while True:
            with self._cond:
                pending = [e for e in self._events if e["seq"] > last]
                if not pending:
                    if self.status in ("done", "failed", "cancelled"):
                        return
                    self._cond.wait(timeout)
                    pending = [e for e in self._events if e["seq"] > last]
            if not pending:
                # Never suspend the generator holding the condition: a slow SSE client
                # must not prevent the importer from publishing its next update.
                yield {"seq": last, "keepalive": True}
                continue
            for e in pending:
                last = e["seq"]
                yield e


class JobManager:
    def __init__(self, library: Library):
        self.lib = library
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [j.snapshot() for j in sorted(self.jobs.values(), key=lambda j: -j.created)]

    def get(self, job_id: str) -> Job:
        with self._lock:
            return self.jobs[job_id]

    def _start(
        self, kind: str, request: dict[str, Any], work: Callable[[Job, ProgressFn], dict[str, Any]]
    ) -> Job:
        job = Job(id=uuid.uuid4().hex[:10], kind=kind, request=request)
        with self._lock:
            # one job at a time keeps memory and disk I/O predictable
            if any(j.status in ("queued", "running") for j in self.jobs.values()):
                raise RuntimeError("another import or export is already running")
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, work), name=f"{kind}-{job.id}", daemon=True).start()
        return job

    def start_import(self, req: ImportRequest) -> Job:
        def work(job: Job, progress: ProgressFn) -> dict[str, Any]:
            res = run_import(self.lib, req, progress, job.cancel)
            job.warnings = res.warnings
            return {
                "dataset_id": res.ref.id,
                "name": res.manifest.name,
                "seconds": round(res.seconds, 1),
                "stats": res.manifest.stats,
            }

        request = {
            "sumstats": str(req.sumstats),
            "annotation": str(req.annotation) if req.annotation else None,
            "name": req.name,
            "dictionary": req.dictionary,
            "profile": req.profile,
            "build": req.build,
        }
        return self._start("import", request, work)

    def start_export(self, dataset_id: str, out: Path) -> Job:
        ref = self.lib.get(dataset_id)
        name = ref.manifest().name

        def work(job: Job, progress: ProgressFn) -> dict[str, Any]:
            t0 = time.time()
            path = export_bundle(ref, out, progress, job.cancel)
            return {
                "dataset_id": ref.id,
                "name": name,
                "path": str(path),
                "bytes": path.stat().st_size,
                "seconds": round(time.time() - t0, 1),
            }

        return self._start("export", {"dataset_id": ref.id, "name": name, "out": str(out)}, work)

    def start_import_bundle(self, bundle: Path, make_current: bool = True, name: str | None = None) -> Job:
        def work(job: Job, progress: ProgressFn) -> dict[str, Any]:
            t0 = time.time()
            ref = import_bundle(self.lib, bundle, progress, job.cancel, make_current=make_current, name=name)
            m = ref.manifest()
            job.warnings = list(m.warnings)
            return {
                "dataset_id": ref.id,
                "name": m.name,
                "seconds": round(time.time() - t0, 1),
                "stats": m.stats,
            }

        return self._start("import-bundle", {"bundle": str(bundle), "name": name or bundle.name}, work)

    def _run(self, job: Job, work: Callable[[Job, ProgressFn], dict[str, Any]]) -> None:
        def progress(step: str, done: int, total: int, message: str) -> None:
            job._emit(step=step, done=done, total=total, message=message)

        job._emit(status="running", started=time.time())
        try:
            result = work(job, progress)
            job._emit(
                status="done",
                finished=time.time(),
                step="done",
                done=job.total,
                message="",
                warnings=job.warnings,
                result=result,
            )
        except ImportCancelledError:
            job._emit(status="cancelled", finished=time.time(), message="cancelled")
        except Exception as e:
            job._emit(
                status="failed",
                finished=time.time(),
                error=f"{type(e).__name__}: {e}",
                message=traceback.format_exc(limit=3),
            )

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status in ("queued", "running"):
            job.cancel.set()
        return job
