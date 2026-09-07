"""Shared fixtures: a synthetic dataset built with the real pipeline, served by the real app."""
from __future__ import annotations

import importlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tests.fixtures.make_synthetic import make_synthetic  # noqa: E402


@pytest.fixture(scope="session")
def synthetic(tmp_path_factory):
    """Synthetic input files + the DuckDB built from them by scripts/build_db.py."""
    import build_db

    out = tmp_path_factory.mktemp("synthetic")
    info = make_synthetic(str(out), seed=0)
    db = str(out / "phewas.duckdb")
    info["counts"] = build_db.build(info["sumstats"], info["annotation"], info["phecodes"], db,
                                    memory_limit="1GB", quiet=True)
    info["db"] = db
    return info


@pytest.fixture(scope="session")
def client(synthetic):
    """FastAPI TestClient bound to the synthetic database."""
    from fastapi.testclient import TestClient

    os.environ["IEI_PHEWAS_DB"] = synthetic["db"]
    sys.modules.pop("app", None)  # app connects at import time
    app_module = importlib.import_module("app")
    with TestClient(app_module.app) as c:
        yield c
