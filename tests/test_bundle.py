"""`.phewasds` bundles: export/import round trip, integrity, CLI and API jobs."""

import hashlib
import json
import shutil
import tarfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from phewas_core.bundle import (
    BUNDLE_SUFFIX,
    BundleError,
    export_bundle,
    import_bundle,
    inspect_bundle,
    read_index,
)
from phewas_core.registry import Library
from phewas_server.app import create_app
from phewas_server.settings import Settings


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def bundle(library, tmp_path_factory):
    out = tmp_path_factory.mktemp("bundles")
    ref = library.current()
    events = []
    path = export_bundle(ref, out, lambda s, d, t, m: events.append((s, d, t)))
    assert path.suffix == BUNDLE_SUFFIX and path.name.startswith("synthetic")
    assert {e[0] for e in events} == {"hash", "export"} and events[-1][1] == events[-1][2]
    return path


def test_bundle_layout_and_index(bundle, library):
    with tarfile.open(bundle, "r:") as tar:
        names = [m.name for m in tar.getmembers()]
    assert names[0] == "phewasds.json" and "dataset.duckdb" in names and "manifest.json" in names
    idx = read_index(bundle)
    assert idx["dataset_id"] == library.current().id and idx["format"] == 1
    assert idx["files"]["dataset.duckdb"]["sha256"] == sha(library.current().db_path)


def test_inspect_reports_contents_and_duplicates(bundle, library, tmp_path):
    info = inspect_bundle(bundle, library)
    assert (
        info["exists"]
        and info["stats"]["n_variants"] > 0
        and [c["id"] for c in info["cohorts"]] == ["META", "AoU", "UKBB"]
    )
    assert info["problems"] and "already in the library" in info["problems"][0]
    assert inspect_bundle(bundle, Library(tmp_path / "empty"))["problems"] == []
    assert inspect_bundle(tmp_path / "nope.phewasds")["problems"] == [
        "not a file: " + str(tmp_path / "nope.phewasds")
    ]


def test_round_trip_keeps_id_and_bytes(bundle, library, tmp_path):
    lib2 = Library(tmp_path / "home2")
    ref = import_bundle(lib2, bundle, name="from bundle")
    assert ref.id == library.current().id
    assert sha(ref.db_path) == sha(library.current().db_path)
    m = ref.manifest()
    assert m.name == "from bundle" and any("imported from bundle" in w for w in m.warnings)
    assert lib2.current().id == ref.id and (ref.dir / "import.log").exists()
    with pytest.raises(BundleError, match="already in the library"):
        import_bundle(lib2, bundle)


def test_corrupted_or_foreign_files_are_refused(bundle, tmp_path, synthetic):
    data = bytearray(bundle.read_bytes())
    data[len(data) // 2] ^= 0xFF  # inside dataset.duckdb (tar pads the end with zero blocks)
    bad = tmp_path / "bad.phewasds"
    bad.write_bytes(data)
    lib = Library(tmp_path / "home3")
    with pytest.raises(BundleError, match="checksum"):
        import_bundle(lib, bad)
    assert lib.list() == [] and not list(lib.datasets_dir.glob("*"))
    with pytest.raises(BundleError, match="not a PheWAS dataset bundle"):
        import_bundle(lib, Path(synthetic["annotation"]))
    newer = tmp_path / "newer.phewasds"
    with tarfile.open(newer, "w") as tar:
        payload = json.dumps({"format": 1, "dataset_id": "x", "schema_version": 999, "files": {}}).encode()
        info = tarfile.TarInfo("phewasds.json")
        info.size = len(payload)
        import io

        tar.addfile(info, io.BytesIO(payload))
    with pytest.raises(BundleError, match="newer"):
        read_index(newer)


def test_cli_export_and_import_bundle(library, tmp_path, capsys):
    from phewas_core.cli import main

    out = tmp_path / "cli.phewasds"
    assert main(["--home", str(library.home), "export", str(out), "--quiet"]) == 0
    assert "exported" in capsys.readouterr().out and out.exists()
    home2 = tmp_path / "home_cli"
    assert main(["--home", str(home2), "import-bundle", str(out), "--name", "cli import", "--quiet"]) == 0
    assert "cli import" in capsys.readouterr().out
    assert Library(home2).current().manifest().name == "cli import"


def _wait(api, job_id, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = api.get(f"/api/v1/jobs/{job_id}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_api_export_then_import_bundle(library, tmp_path):
    home = tmp_path / "home_api"
    shutil.copytree(library.home, home)
    app = create_app(Settings(home=home, token="t", static_dir=None))
    with TestClient(app, headers={"Authorization": "Bearer t"}) as api:
        ds = api.get("/api/v1/library").json()["current"]
        r = api.post(f"/api/v1/datasets/{ds}/export", json={"path": str(tmp_path / "exports")})
        assert r.status_code == 202, r.text
        j = _wait(api, r.json()["id"])
        assert j["status"] == "done" and j["kind"] == "export", j
        path = Path(j["result"]["path"])
        assert path.exists() and j["result"]["bytes"] == path.stat().st_size
        assert (
            api.post(
                f"/api/v1/datasets/{ds}/export", json={"path": str(tmp_path / "nowhere" / "x.phewasds")}
            ).status_code
            == 400
        )
        assert api.post("/api/v1/datasets/nope/export", json={"path": str(tmp_path)}).status_code == 404

        info = api.post("/api/v1/import/inspect-bundle", json={"path": str(path)}).json()
        assert info["dataset_id"] == ds and info["problems"]  # duplicate in this library
        api.delete(f"/api/v1/datasets/{ds}")
        assert api.post("/api/v1/import/inspect-bundle", json={"path": str(path)}).json()["problems"] == []
        r = api.post("/api/v1/import/bundle", json={"path": str(path), "name": "restored"})
        assert r.status_code == 202
        j = _wait(api, r.json()["id"])
        assert j["status"] == "done" and j["result"]["name"] == "restored" and j["result"]["dataset_id"] == ds
        lib = api.get("/api/v1/library").json()
        assert lib["current"] == ds and any(d["id"] == ds for d in lib["datasets"])
        assert (
            api.post("/api/v1/import/bundle", json={"path": str(tmp_path / "missing.phewasds")}).status_code
            == 400
        )
