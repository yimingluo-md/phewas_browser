# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [Unreleased]

### Fixed — post-migration audit
- `phewas serve` launches the current server and supports importing into an empty library.
- Static frontend requests cannot escape the frontend directory, including through symlinks.
- CSV preview and import agree on the delimiter; long-format imports accept missing optional statistics.
- Imports accept library paths containing apostrophes, honor cancellation while hashing, and close
  DuckDB before removing failed imports on Windows. Failed logs include the error.
- Concurrent library operations in the server are serialized; reordering does not duplicate datasets,
  and renaming keeps in-flight database requests usable.
- Page navigation, import inspection and plots discard stale responses. Import progress continues
  after a dropped stream, releases subscriptions when navigating away, and permits restarting after cancellation.
- Search ignores responses to older queries; launch tokens still work when browser storage is disabled.
- SSE keepalives cannot hold the importer lock while waiting for a client to consume them.
- The Windows parent watchdog preserves 64-bit handles. Desktop startup times out even for a silent
  sidecar, and Show Data Folder uses the server's actual library location.
- The migration comparison detects numeric values lost to NULL instead of reporting them as identical.
- Browser regression tests run in CI; Python tests also run on Windows.

### Phase 1: core extraction

### Added
- `packages/phewas_core`: the new engine, no web dependencies.
  - `schema.py` — schema v1: cohort-agnostic **long** `assoc` table (ADR-0001), `cohort`, `trait`,
    `variant`, wide `annotation` generated from the field registry, derived `variant_index` /
    `gene_summary` / `rsid_map`, embedded manifest.
  - `fields.py` — the annotation field registry (53 fields); importer SQL, API metadata and
    future UI columns all derive from it.
  - `profiles.py` + `builtin/profiles/` — JSON import profiles; `regenie-meta-wide` matches the
    current meta-analysis layout exactly, `long` accepts one row per variant/trait/cohort.
    Header auto-detection.
  - `dictionaries.py` — built-in phecode v1.2; any `trait,description[,category,category_ord,color]` CSV.
  - `importer.py` — sniff → stage (sorted) → variants/cohorts → chunked unpivot with progress →
    VEP annotation → derived tables → manifest with source hashes → atomic finalize.
    Memory bounded by DuckDB `memory_limit` (default half of RAM).
  - `registry.py` — the dataset library (`registry.json`, `datasets/<id>/{manifest.json,dataset.duckdb,import.log}`)
    under `~/Library/Application Support/PheWAS Browser` (`$PHEWAS_HOME` overrides). Immutable
    datasets; previous versions kept until removed.
  - `query.py` — cohort-/field-agnostic query layer (per-cohort stats as `{cohort: {stat: value}}`).
  - `legacy_api.py` — adapter producing today's JSON shapes so the unchanged frontend works.
  - `cli.py` — `phewas import | list | info | current | remove | profiles | serve`.
- `docs/adr/0001-storage-layout.md` with the benchmark on the real dataset (`benchmarks/storage_layout/`).
- Tests: 53 total — API contract now runs against **both** the legacy database and a phewas_core
  dataset, plus value-for-value equivalence tests and core unit/integration tests.

### Fixed (found by the first real import)
- VEP rows without a gene symbol (regulatory/motif features) are skipped by the annotation importer.
- Non-finite statistics (`Inf` odds ratios from diverged Firth fits: 26,472 META / 25,273 AoU /
  1,268 UKBB rows in the IEI dataset) are stored as missing and counted in a manifest warning;
  the legacy API already returned them as `null`.
- `variant_index.top_or` is the top trait's own OR even when that OR is missing.
- `scripts/compare_with_legacy.py` checks a dataset value-for-value against the legacy database.

### Changed
- `app.py` serves a phewas_core dataset when given one (`PHEWAS_DATASET`, `IEI_PHEWAS_DB`, or the
  library's current dataset) and still serves the legacy `data/phewas.duckdb`. Bundles now ship
  `packages/` (make_bundle.sh, launch.sh updated).

## [0.2.0] — 2026-09-07 — Phase 0: foundations

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
