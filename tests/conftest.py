"""Shared fixtures: a synthetic dataset built with the real pipeline, served by the real app."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "tests", "legacy")):
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
    info["counts"] = build_db.build(
        info["sumstats"], info["annotation"], info["phecodes"], db, memory_limit="1GB", quiet=True
    )
    info["db"] = db
    return info


@pytest.fixture(scope="session")
def library(synthetic, tmp_path_factory):
    """A phewas_core library with the synthetic inputs imported through the new pipeline."""
    from phewas_core.importer import ImportRequest, run_import
    from phewas_core.registry import Library

    home = tmp_path_factory.mktemp("phewas_home")
    lib = Library(home)
    res = run_import(
        lib,
        ImportRequest(
            sumstats=Path(synthetic["sumstats"]),
            name="synthetic",
            annotation=Path(synthetic["annotation"]),
            memory_limit="800MB",
            threads=2,
            hash_sources=False,
        ),
    )
    synthetic["core_db"] = str(res.ref.db_path)
    synthetic["import_result"] = res
    return lib
