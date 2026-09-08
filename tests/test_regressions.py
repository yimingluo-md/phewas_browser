"""Regression cases from the post-migration audit (synthetic data only)."""

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from phewas_core.importer import ImportCancelledError, ImportRequest, inspect_sumstats, run_import
from phewas_core.query import Dataset
from phewas_core.registry import Library
from phewas_server.app import create_app
from phewas_server.settings import Settings


def long_input(tmp_path: Path, delimiter: str = "\t") -> Path:
    path = tmp_path / "long.csv"
    path.write_text(
        delimiter.join(["variant_id", "gene", "trait", "cohort", "p"])
        + "\n"
        + delimiter.join(["1:100:A:T", "GENE", "T1", "META", "0.01"])
        + "\n"
    )
    return path


def dictionary(tmp_path: Path) -> str:
    path = tmp_path / "dictionary.csv"
    path.write_text("trait,description\nT1,Trait one\n")
    return str(path)


@pytest.mark.parametrize("delimiter", ["\t", ","])
def test_minimal_long_layout_preview_and_import_agree(tmp_path, delimiter):
    source = long_input(tmp_path, delimiter)
    preview = inspect_sumstats(source)
    assert preview["problems"] == []
    assert preview["preview"][0]["p"] == "0.01"
    result = run_import(
        Library(tmp_path / "home"),
        ImportRequest(
            source, "minimal", dictionary=dictionary(tmp_path), memory_limit="500MB", hash_sources=False
        ),
    )
    ds = Dataset(result.ref.db_path)
    try:
        assert ds.variant_page("1:100:A:T")["associations"][0]["cohorts"]["META"]["p"] == 0.01
        assert result.manifest.statistics == ["p"]
    finally:
        ds.close()


def test_import_accepts_apostrophe_in_library_path(tmp_path, synthetic):
    lib = Library(tmp_path / "Researcher's library")
    result = run_import(
        lib,
        ImportRequest(Path(synthetic["sumstats"]), "quoted path", memory_limit="500MB", hash_sources=False),
    )
    assert lib.current().id == result.ref.id


def test_cancel_during_source_hash_discards_import(tmp_path, synthetic):
    lib = Library(tmp_path / "home")
    cancel = threading.Event()

    def progress(step, done, total, message):
        if step == "hash":
            cancel.set()

    with pytest.raises(ImportCancelledError):
        run_import(
            lib, ImportRequest(Path(synthetic["sumstats"]), "cancel", memory_limit="500MB"), progress, cancel
        )
    assert lib.list() == []
    assert not list(lib.datasets_dir.glob("*.partial"))


@pytest.mark.parametrize("kind", ["sumstats", "annotation"])
def test_inspect_invalid_input_reports_problem_instead_of_500(tmp_path, kind):
    source = tmp_path / "broken.tsv.gz"
    source.write_bytes(b"not a gzip stream\x00\xff")
    app = create_app(Settings(home=tmp_path / "home", token="test", static_dir=None))
    with TestClient(app, raise_server_exceptions=False) as client:
        for path in (source, tmp_path):
            response = client.post(
                "/api/v1/import/inspect", headers={"Authorization": "Bearer test"}, json={kind: str(path)}
            )
            assert response.status_code == 200
            assert response.json()[kind]["problems"]


def test_static_routes_cannot_read_outside_frontend(tmp_path):
    static = tmp_path / "web"
    static.mkdir()
    (static / "assets").mkdir()
    (static / "index.html").write_text("<html>frontend</html>")
    (tmp_path / "private.txt").write_text("private sentinel")
    (static / "link.txt").symlink_to(tmp_path / "private.txt")
    app = create_app(Settings(home=tmp_path / "home", token="test", static_dir=static))
    with TestClient(app) as client:
        for url in ("/%2e%2e/private.txt", "/link.txt"):
            response = client.get(url)
            assert "private sentinel" not in response.text
        assert client.get("/some/spa/route").text == "<html>frontend</html>"


def test_reorder_deduplicates_dataset_ids(tmp_path, synthetic):
    lib = Library(tmp_path / "home")
    result = run_import(
        lib, ImportRequest(Path(synthetic["sumstats"]), "order", memory_limit="500MB", hash_sources=False)
    )
    lib.reorder([result.ref.id, result.ref.id])
    assert [r.id for r in lib.list()] == [result.ref.id]


def test_concurrent_import_registration_keeps_every_dataset(tmp_path, library):
    lib = Library(tmp_path / "home")
    manifest = library.current().manifest()
    ids = [lib.new_id() for _ in range(12)]
    for dataset_id in ids:
        partial = lib.partial_dir(dataset_id)
        manifest.save(partial / "manifest.json")
        (partial / "dataset.duckdb").touch()
    barrier = threading.Barrier(len(ids))

    def finalize(dataset_id):
        barrier.wait(timeout=5)
        lib.finalize(dataset_id)

    with ThreadPoolExecutor(max_workers=len(ids)) as pool:
        list(pool.map(finalize, ids))
    assert {ref.id for ref in lib.list()} == set(ids)


def test_windows_parent_watchdog_preserves_64_bit_handles(monkeypatch):
    import ctypes
    from types import SimpleNamespace

    import phewas_server.__main__ as entry

    handle = 0x123456789ABC
    # Model WinDLL's default int return type, which truncates a HANDLE on 64-bit Windows.
    open_process = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)(
        lambda access, inherit, pid: handle
    )
    open_process.restype = ctypes.c_int

    def exit_code(received, code):
        code[0] = 259
        return int(received == handle)

    get_exit = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))(exit_code)
    close = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)(lambda received: 1)
    kernel = SimpleNamespace(OpenProcess=open_process, GetExitCodeProcess=get_exit, CloseHandle=close)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False)
    monkeypatch.setattr(entry, "sys", SimpleNamespace(platform="win32"))
    assert entry._parent_alive(1234)


def test_cli_serve_opens_new_server_even_with_empty_library(tmp_path, monkeypatch):
    import phewas_server.__main__ as server
    from phewas_core.cli import main

    calls = []
    monkeypatch.setattr(server, "main", lambda argv: calls.append(argv) or 0)
    assert main(["--home", str(tmp_path), "serve", "--port", "8561"]) == 0
    assert calls == [["--home", str(tmp_path), "--port", "8561"]]


def test_sse_keepalive_does_not_block_import_progress():
    from phewas_server.jobs import Job

    job = Job(id="test", kind="import", request={}, status="running")
    events = job.events(timeout=0.01)
    assert next(events)["keepalive"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        update = pool.submit(job._emit, step="stage")
        try:
            update.result(timeout=1)
        finally:
            events.close()


def test_rename_keeps_inflight_dataset_connection_usable(tmp_path, library):
    import shutil

    from phewas_server.app import DatasetCache

    shutil.copytree(library.home, tmp_path / "home")
    lib = Library(tmp_path / "home")
    cache = DatasetCache(lib)
    ref = lib.current()
    ds = cache.get(ref.id)
    try:
        lib.update_manifest(ref.id, name="renamed")
        cache.refresh_manifest(ref.id)
        assert ds.meta()["manifest"]["name"] == "renamed"
    finally:
        cache.drop(ref.id)
