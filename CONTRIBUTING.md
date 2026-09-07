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
uv run python tests/fixtures/make_synthetic.py /tmp/syn      # inspect the fixture inputs
uv run python scripts/build_db.py --sumstats /tmp/syn/sumstats.tsv.gz \
    --annotation /tmp/syn/annotation.tsv --out /tmp/syn/phewas.duckdb --memory-limit 1GB
IEI_PHEWAS_DB=/tmp/syn/phewas.duckdb uv run uvicorn app:app --port 8555   # browse the fixture
```

## Conventions

- **Versions**: `duckdb`, `fastapi`, `uvicorn` are pinned identically in
  `pyproject.toml`, `uv.lock` and `requirements.lock.txt` (the latter feeds the
  bundled offline runtimes). Bump all three together, then rebuild runtimes.
- **Lint**: `ruff check` must pass in CI. `ruff format` is not enforced on the
  legacy files (`app.py`, `scripts/`, `static/`); it is required for everything
  under `packages/` once Phase 1 starts.
- **Tests**: every bug fix in the pipeline or API gets a test against the synthetic
  fixture first. Extend `make_synthetic.py` when a new awkward input case is found.
- **Commits**: short imperative subject, body explains *why*. Update `CHANGELOG.md`
  under *Unreleased* in the same commit as a user-visible change.
- **Architecture decisions** are recorded in `docs/ARCHITECTURE_PLAN.md` (§4) and,
  from Phase 1 on, as one file per decision in `docs/adr/`.

## Repository map (Phase 0)

| Path | Role |
|---|---|
| `app.py`, `static/`, `launch.sh`, `*.command`, `*.bat` | today's runnable browser — keep working until the native shell (Phase 3) replaces it |
| `scripts/build_db.py` | import pipeline; CLI flags for inputs/outputs |
| `tests/` | pytest suite + synthetic fixture generator |
| `docs/ARCHITECTURE_PLAN.md` | where this is going and why |
| `.github/workflows/ci.yml` | lint + tests on Linux and macOS |
