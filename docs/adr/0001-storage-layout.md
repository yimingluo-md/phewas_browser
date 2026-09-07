# ADR-0001: Store associations in long format (one row per variant × trait × cohort)

*Status: accepted · 2026-09-07*

## Context

The current `assoc` table is wide: one row per (variant, gene, trait) with a fixed
set of columns per cohort (`or_meta, p_meta, …, or_aou, …, or_ukbb, …`). Every new
cohort or statistic is a schema, API and UI change. The plan (§2.2) proposed a
cohort-agnostic layout and deferred the choice between three candidates to a
benchmark on the real IEI dataset (68.8 M wide rows, 43,257 variants × 50 genes ×
1,715 phecodes, 3 cohorts of which META is always present):

1. **Long** — `assoc(variant_id, gene, trait, cohort, or, p, cases, case_carriers, controls, ctrl_carriers)`, sorted `(gene, variant_id, trait, cohort)`. Rows for absent cohorts are not stored.
2. **MAP** — one row per (variant, gene, trait) with `stats MAP(cohort → STRUCT(or, p, …))`.
3. **Wide with metadata** — keep today's layout, describe the column prefixes in the manifest.

## Measurements

Machine: 4-core Linux VM with DuckDB `memory_limit` 1 GB, database on a network
mount (i.e. a pessimistic environment; a MacBook reads ~2–5× faster). DuckDB 1.5.5.

**Conversion.** Wide → long + MAP for all 50 genes: 80 s total in per-gene chunks
of ≤150 variants (≈250 k wide rows), never exceeding 1 GB. Long has 154 M rows (not
3 × 68.8 M, because single-cohort rows only produce two rows).

**Size of the `assoc` table alone** (persistent blocks × 256 KiB):

| layout | size | vs wide |
|---|---|---|
| wide | 3.04 GB | — |
| long | 3.50 GB | +15 % |
| MAP  | 3.30 GB | +8 % |

In the long table the two DOUBLE columns (`or`, `p`, ALPRD-compressed) are 2.7 GB of
the 3.5 GB; the key columns (`gene`, `variant_id`, `trait`, `cohort`) compress to
constant/dictionary segments because of the sort order.

**Queries** (median of warm runs; first run in parentheses):

| query | wide | long | MAP |
|---|---|---|---|
| variant page, all traits for one variant (≈1.4–1.7 k traits) | 1.8 ms (8) | 2.0 ms (5) — 3.4 k rows | 6 ms (9) |
| same, pivoted to `{trait → {cohort → stats}}` in SQL | — | 6.5 ms | — |
| gene index rebuild, largest gene (KMT2D, 9.6 M wide rows): per-variant `min(p)`, `arg_min` | 35 ms (178) | 51 ms (135) | 167 ms (312) |
| trait slice: all KMT2D variants for one phecode | 20 ms (80) | 30 ms (77) | 64 ms (70) |
| dataset-wide top-20 hits (full scan) | 4 ms\* | 440 ms (650) | 1.6 s (1.9) |

\*The wide scan benefits from zonemap pruning on `p_meta`; in the long table the
`cohort = 'META'` filter defeats that. 0.4 s for a whole-dataset scan is still
acceptable for an interactive feature, and a `hits` summary table can be derived
at import if it is needed often.

Also checked: `cases`/`controls` are **not** constant per (trait, cohort) — all
1,715 traits show per-variant variation (sample exclusions per variant), so they
cannot be normalised out into a trait table.

## Decision

**Long format.** It is within 15 % of the wide table on disk, at parity on the
two query patterns that drive every page (variant page, gene index), and it is the
only candidate where a new cohort or statistic is data rather than schema. The
pivot to `{cohort → stats}` is done in the API layer (Python), not SQL — 3.4 k rows
per variant page pivot in well under a millisecond and keep the SQL trivial.

MAP is rejected: slowest on every aggregate, awkward SQL (`stats['META'].p`), and
DuckDB cannot use zonemaps inside a MAP. Wide-with-metadata is rejected because
it only moves the hard-coding from code into the manifest; every cohort still
adds columns, and per-cohort filtering needs generated SQL.

## Consequences

- `phewas_core.schema` defines the long `assoc` table plus `cohort` and `trait`
  tables; the importer unpivots wide inputs via the profile's `cohort_columns`
  regex and writes long inputs as-is.
- Derived tables (`variant_index`, `gene_summary`) are computed on the cohort the
  manifest marks `primary` (META when present).
- Imports run in per-gene (and, for large genes, per-variant-range) chunks so
  memory stays bounded and the job is resumable — the benchmark script is the
  template.
- Whole-dataset queries (top hits, trait-across-genes) should read a derived
  summary table, not scan `assoc`.
- The optional `beta`, `se`, `aaf`, `mac` statistics are additional nullable
  columns in the same table; the manifest's `statistics` list says which are populated.
