# Contributing / developer setup

Everything below runs without any real summary statistics: the test-suite builds a
tiny synthetic dataset (`tests/fixtures/make_synthetic.py`) through the real
pipeline and exercises the real API against it. **Never commit real data or a
DuckDB built from it** — `.gitignore` blocks `data/*.duckdb`, but stay alert.

## One-time setup

```bash
# Python 3.12 + locked dependencies, managed by uv (https://docs.astral.sh/uv/)
curl -LsSf https://astral.sh/uv/install.sh | sh     # if uv is not installed
uv sync                                             # creates .venv from uv.lock
```

## Everyday commands

```bash
uv run pytest -q                 # tests on the synthetic dataset (< 2 s)
uv run ruff check .              # lint
uv run ruff format packages tests
uv run mypy                      # strict typing on packages/
uv run phewas --help             # dataset library CLI (import / list / info / serve ...)
uv run python tests/fixtures/make_synthetic.py /tmp/syn      # inspect the fixture inputs
uv run python scripts/build_db.py --sumstats /tmp/syn/sumstats.tsv.gz \
    --annotation /tmp/syn/annotation.tsv --out /tmp/syn/phewas.duckdb --memory-limit 1GB
IEI_PHEWAS_DB=/tmp/syn/phewas.duckdb uv run uvicorn app:app --port 8555   # browse the fixture
```

## Conventions

- **Versions**: `duckdb`, `fastapi`, `uvicorn` are pinned identically in
  `pyproject.toml`, `uv.lock` and `requirements.lock.txt` (the latter feeds the
  bundled offline runtimes). Bump all three together, then rebuild runtimes.
- **Lint**: `ruff check` and `mypy` must pass in CI; `ruff format` is the style for `packages/`,
  `scripts/` and `tests/`.
- **Tests**: every bug fix in the pipeline or API gets a test against the synthetic
  fixture first. Extend `make_synthetic.py` when a new awkward input case is found.
- **Commits**: short imperative subject, body explains *why*. Update `CHANGELOG.md`
  under *Unreleased* in the same commit as a user-visible change.
- **Architecture decisions** are recorded in `docs/ARCHITECTURE_PLAN.md` (§4) and,
  from Phase 1 on, as one file per decision in `docs/adr/`.

## Repository map (Phase 1)

| Path | Role |
|---|---|
| `packages/phewas_core/` | the engine: schema, field registry, profiles, importer, registry, query layer, CLI |
| `app.py`, `static/`, `launch.sh`, `*.command`, `*.bat` | today's runnable browser (legacy API shape via `legacy_api.py`) — keeps working until the native shell (Phase 3) replaces it |
| `scripts/build_db.py` | legacy one-off pipeline; kept only as the reference the equivalence tests compare against |
| `tests/` | pytest suite + synthetic fixture generator; `test_equivalence.py` pins new == legacy |
| `benchmarks/` | reproducible measurements behind ADRs |
| `docs/ARCHITECTURE_PLAN.md`, `docs/adr/` | where this is going and why; one file per decision |
| `.github/workflows/ci.yml` | lint + mypy + tests on Linux and macOS |

## Adding things

- **An annotation field**: one `Field(...)` entry in `packages/phewas_core/phewas_core/fields.py`;
  re-import the dataset. Importer SQL, API metadata and (from Phase 2) UI columns follow.
- **A sumstats layout**: a JSON profile in `builtin/profiles/` (or `<home>/profiles/` for a
  user); see `regenie-meta-wide.json`. Statistics must be among `manifest.STATISTICS`.
- **A phenotype dictionary**: any CSV with `trait,description[,category,category_ord,color]`
  passed to `phewas import --dictionary`.
- **A schema change**: bump `SCHEMA_VERSION`, add a migration note in `schema.py`, and make
  `Dataset` refuse (with a clear message) datasets it cannot read.
