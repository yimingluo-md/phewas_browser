"""Background import jobs with progress events (polled or streamed as SSE)."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from phewas_core.importer import ImportCancelledError, ImportRequest, run_import
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

    def start_import(self, req: ImportRequest, make_current: bool = True) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:10],
            kind="import",
            request={
                "sumstats": str(req.sumstats),
                "annotation": str(req.annotation) if req.annotation else None,
                "name": req.name,
                "dictionary": req.dictionary,
                "profile": req.profile,
                "build": req.build,
            },
        )
        with self._lock:
            # one import at a time keeps memory predictable
            if any(j.status in ("queued", "running") for j in self.jobs.values()):
                raise RuntimeError("another import is already running")
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, req), name=f"import-{job.id}", daemon=True).start()
        return job

    def _run(self, job: Job, req: ImportRequest) -> None:
        def progress(step: str, done: int, total: int, message: str) -> None:
            job._emit(step=step, done=done, total=total, message=message)

        job._emit(status="running", started=time.time())
        try:
            res = run_import(self.lib, req, progress, job.cancel)
            job._emit(
                status="done",
                finished=time.time(),
                step="done",
                done=job.total,
                message="",
                warnings=res.warnings,
                result={
                    "dataset_id": res.ref.id,
                    "name": res.manifest.name,
                    "seconds": round(res.seconds, 1),
                    "stats": res.manifest.stats,
                },
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
