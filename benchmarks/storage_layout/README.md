# Storage-layout benchmark (ADR-0001)

Converts the existing wide `assoc` table of a real `phewas.duckdb` into the long
(one row per variant × trait × cohort) and MAP (one row per variant × trait, cohorts
in a `MAP(cohort → STRUCT)`) layouts, then times the browser's query patterns.

```bash
# resumable, per-gene chunks; safe with ~1 GB of DuckDB memory
uv run python benchmarks/storage_layout/build_long_and_map.py 140   # seconds budget; rerun until "remaining: 0"
uv run python benchmarks/storage_layout/query_bench.py
```

Paths are read from `~/mnt/phewas_browser/data/phewas.duckdb` and written to `~/bench/`;
edit the constants at the top of each script for another machine. Results and the
decision are in `docs/adr/0001-storage-layout.md`. Requires the real dataset (not in git).
