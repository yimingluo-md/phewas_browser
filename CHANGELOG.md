# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [Unreleased] — Phase 0: foundations

### Added
- Git repository, `.gitignore` excluding databases, bundled runtimes and builds.
- `docs/ARCHITECTURE_PLAN.md`: Mac app (Tauri 2 + Python sidecar) architecture and roadmap.
- `pyproject.toml` + `uv.lock` (Python 3.12, pinned duckdb/fastapi/uvicorn), ruff and pytest config.
- Synthetic dataset generator (`tests/fixtures/make_synthetic.py`) in the real input layouts.
- Test-suite: import pipeline (`tests/test_build_db.py`) and HTTP API (`tests/test_api.py`), 24 tests.
- GitHub Actions CI (lint + tests on ubuntu and macos).
- `CONTRIBUTING.md`, this changelog.

### Changed
- `scripts/build_db.py` accepts `--sumstats/--annotation/--phecodes/--out/--memory-limit`
  (defaults unchanged) and exposes `build()` for tests.
- `app.py` honours `IEI_PHEWAS_DB` to point the server at another database (default unchanged).

## [0.1.0] — 2026-08-25 (pre-git baseline)
- IEI PheWAS Browser as distributed to collaborators: FastAPI + DuckDB backend, vanilla JS +
  Plotly frontend, self-contained Mac (.app) and Windows (.bat) bundles.
