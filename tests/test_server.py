"""API v1 contract of phewas_server: auth, library, dataset pages, import jobs, file picker."""

import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from phewas_server.app import create_app
from phewas_server.settings import Settings

TOKEN = "test-token-123"


@pytest.fixture(scope="module")
def home(library, tmp_path_factory):
    """A private copy of the session library so this module can import/rename/delete freely."""
    dst = tmp_path_factory.mktemp("server_home")
    shutil.copytree(library.home, dst, dirs_exist_ok=True)
    return dst


@pytest.fixture(scope="module")
def api(home):
    app = create_app(Settings(home=home, token=TOKEN, static_dir=None))
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


@pytest.fixture(scope="module")
def ds_id(api):
    return api.get("/api/v1/library").json()["current"]


# ---------------------------------------------------------------- auth
def test_health_is_open_and_everything_else_needs_a_token(home):
    app = create_app(Settings(home=home, token=TOKEN, static_dir=None))
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/health").json()["application"] == "PheWAS Browser"
        assert c.get("/api/v1/library").status_code == 401
        assert c.get("/api/v1/library", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/api/v1/library", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
        assert c.get("/api/v1/library", headers={"X-PheWAS-Token": TOKEN}).status_code == 200
        assert c.get(f"/api/v1/library?token={TOKEN}").status_code == 200
        assert c.get("/").json()["frontend"] == "not built"


# ---------------------------------------------------------------- library + dataset
def test_library_lists_dataset_with_manifest_summary(api, ds_id, synthetic):
    lib = api.get("/api/v1/library").json()
    assert lib["current"] == ds_id
    d = next(d for d in lib["datasets"] if d["id"] == ds_id)
    assert d["name"] == "synthetic" and [c["id"] for c in d["cohorts"]] == ["META", "AoU", "UKBB"]
    assert d["stats"]["n_variants"] == len(synthetic["variants"]) and d["size_bytes"] > 0


def test_dataset_info_meta_search_gene_variant(api, ds_id, synthetic):
    info = api.get(f"/api/v1/datasets/{ds_id}").json()
    assert info["manifest"]["id"] == ds_id and info["primary_cohort"] == "META"
    assert {f["name"] for f in info["fields"]} >= {"cadd_phred", "consequence"}
    assert "done in" in info["log"]

    meta = api.get(f"/api/v1/datasets/{ds_id}/meta").json()
    assert meta["stats"]["n_genes"] == 3 and [c["id"] for c in meta["cohorts"]] == ["META", "AoU", "UKBB"]

    s = api.get(f"/api/v1/datasets/{ds_id}/search", params={"q": "GENE"}).json()["results"]
    assert any(r["type"] == "gene" and r["id"] == "GENEA" for r in s)
    assert api.get(f"/api/v1/datasets/{ds_id}/search").status_code == 422

    g = api.get(f"/api/v1/datasets/{ds_id}/genes/GENEA").json()
    assert g["summary"]["gene"] == "GENEA" and "cohorts" in g["variants"][0]
    assert api.get(f"/api/v1/datasets/{ds_id}/genes/NOPE").status_code == 404

    v = synthetic["variants"][3]
    page = api.get(f"/api/v1/datasets/{ds_id}/variants/{v['name']}", params={"gene": v["gene"]}).json()
    assert page["gene"] == v["gene"] and "META" in page["associations"][0]["cohorts"]
    assert api.get(f"/api/v1/datasets/{ds_id}/variants/1:1:A:T").status_code == 404
    assert api.get("/api/v1/datasets/nope/meta").status_code == 404


def test_rename_updates_manifest_and_info(api, ds_id):
    r = api.patch(f"/api/v1/datasets/{ds_id}", json={"name": "renamed", "notes": "hello"})
    assert r.status_code == 200 and r.json()["name"] == "renamed"
    assert api.get(f"/api/v1/datasets/{ds_id}").json()["manifest"]["name"] == "renamed"
    assert (
        next(d for d in api.get("/api/v1/library").json()["datasets"] if d["id"] == ds_id)["notes"] == "hello"
    )


# ---------------------------------------------------------------- import wizard
def test_profiles_dictionaries_inspect(api, synthetic):
    assert {p["name"] for p in api.get("/api/v1/profiles").json()} >= {"regenie-meta-wide", "long"}
    assert api.get("/api/v1/dictionaries").json()[0]["id"] == "phecode-1.2"
    r = api.post(
        "/api/v1/import/inspect",
        json={"sumstats": synthetic["sumstats"], "annotation": synthetic["annotation"]},
    ).json()
    assert r["sumstats"]["profile"] == "regenie-meta-wide" and [
        c["id"] for c in r["sumstats"]["cohorts"]
    ] == ["META", "AoU", "UKBB"]
    assert r["sumstats"]["problems"] == [] and len(r["sumstats"]["preview"]) == 5
    assert r["annotation"]["problems"] == [] and r["annotation"]["fields_covered"]
    r = api.post("/api/v1/import/inspect", json={"sumstats": "/nope/x.tsv"}).json()
    assert r["sumstats"]["exists"] is False


def _wait(api, job_id, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = api.get(f"/api/v1/jobs/{job_id}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_import_job_runs_streams_and_registers_dataset(api, synthetic):
    r = api.post(
        "/api/v1/import/jobs",
        json={
            "sumstats": synthetic["sumstats"],
            "annotation": synthetic["annotation"],
            "name": "via api",
            "memory_limit": "500MB",
            "make_current": False,
        },
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]
    # SSE stream delivers snapshots until the job finishes
    seen = []
    with api.stream("GET", f"/api/v1/jobs/{job_id}/events") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith("data: "):
                e = json.loads(line[6:])
                if not e.get("keepalive"):
                    seen.append(e)
    assert seen[-1]["status"] == "done", seen[-1]
    assert any(e["step"] == "assoc" and e["total"] > 0 for e in seen)
    j = _wait(api, job_id)
    assert j["result"]["name"] == "via api" and j["result"]["stats"]["n_variants"] == len(
        synthetic["variants"]
    )
    lib = api.get("/api/v1/library").json()
    assert any(d["id"] == j["result"]["dataset_id"] for d in lib["datasets"])
    assert lib["current"] != j["result"]["dataset_id"]  # make_current=False
    assert api.get("/api/v1/jobs").json()[0]["id"] == job_id


def test_import_job_validation_and_failure(api, tmp_path):
    assert api.post("/api/v1/import/jobs", json={"sumstats": "/nope.tsv"}).status_code == 400
    bad = tmp_path / "bad.tsv"
    bad.write_text("a\tb\n1\t2\n")
    r = api.post("/api/v1/import/jobs", json={"sumstats": str(bad), "memory_limit": "300MB"})
    assert r.status_code == 202
    j = _wait(api, r.json()["id"])
    assert j["status"] == "failed" and "ProfileError" in j["error"]


def test_import_job_cancel(api, synthetic, monkeypatch):
    import phewas_core.importer as imp

    # make the job slow enough to cancel: tiny chunks + a pause per chunk
    monkeypatch.setattr(imp, "CHUNK_ROWS", 40)
    orig_step = imp.Importer.step

    def slow_step(self, name, done=0, total=1, msg=""):
        if name == "assoc":
            time.sleep(0.05)
        return orig_step(self, name, done, total, msg)

    monkeypatch.setattr(imp.Importer, "step", slow_step)
    r = api.post(
        "/api/v1/import/jobs",
        json={"sumstats": synthetic["sumstats"], "name": "cancel me", "memory_limit": "300MB"},
    )
    assert r.status_code == 202
    job_id = r.json()["id"]
    time.sleep(0.3)
    assert api.post(f"/api/v1/jobs/{job_id}/cancel").status_code == 200
    j = _wait(api, job_id)
    assert j["status"] == "cancelled"
    assert not any(d["name"] == "cancel me" for d in api.get("/api/v1/library").json()["datasets"])
    home = Path(api.get("/api/v1/library").json()["home"])
    assert not list((home / "datasets").glob("*.partial"))


def test_only_one_import_at_a_time(api, synthetic, monkeypatch):
    import phewas_core.importer as imp

    orig_step = imp.Importer.step

    def slow_step(self, name, done=0, total=1, msg=""):
        time.sleep(0.2)
        return orig_step(self, name, done, total, msg)

    monkeypatch.setattr(imp.Importer, "step", slow_step)
    first = api.post(
        "/api/v1/import/jobs",
        json={
            "sumstats": synthetic["sumstats"],
            "name": "one",
            "memory_limit": "300MB",
            "make_current": False,
        },
    )
    assert first.status_code == 202
    second = api.post(
        "/api/v1/import/jobs",
        json={"sumstats": synthetic["sumstats"], "name": "two", "memory_limit": "300MB"},
    )
    assert second.status_code == 409
    api.post(f"/api/v1/jobs/{first.json()['id']}/cancel")
    _wait(api, first.json()["id"])


# ---------------------------------------------------------------- delete + fs
def test_delete_dataset(api):
    lib = api.get("/api/v1/library").json()
    victim = next(d["id"] for d in lib["datasets"] if d["name"] == "via api")
    r = api.delete(f"/api/v1/datasets/{victim}")
    assert r.status_code == 200 and all(d["id"] != victim for d in r.json()["datasets"])
    assert api.delete(f"/api/v1/datasets/{victim}").status_code == 404


def test_fs_listing(api, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.tsv.gz").write_bytes(b"x")
    (tmp_path / "ignored.png").write_bytes(b"x")
    (tmp_path / ".hidden.tsv").write_bytes(b"x")
    r = api.get("/api/v1/fs", params={"path": str(tmp_path)}).json()
    names = [e["name"] for e in r["entries"]]
    assert names == ["sub", "a.tsv.gz"] and r["parent"] == str(tmp_path.parent) and r["roots"]
    assert api.get("/api/v1/fs", params={"path": str(tmp_path / "nope")}).status_code == 404
    assert api.get("/api/v1/fs").json()["path"] == str(Path.home())
