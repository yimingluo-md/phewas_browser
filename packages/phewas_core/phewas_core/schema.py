"""On-disk DuckDB schema (SCHEMA_VERSION 1) and the SQL that derives the summary tables.

Layout decisions are recorded in docs/adr/0001-storage-layout.md: associations are
long over cohort; annotation is one wide row per (variant, gene) whose columns come
from the field registry (fields.py); variant_index / gene_summary are computed on
the manifest's primary cohort.
"""

from __future__ import annotations

import duckdb

from .fields import annotation_ddl_columns

ASSOC_COLUMNS = (
    ("variant_id", "VARCHAR"),
    ("gene", "VARCHAR"),
    ("trait", "VARCHAR"),
    ("cohort", "VARCHAR"),
    ("beta", "DOUBLE"),
    ("se", "DOUBLE"),
    ('"or"', "DOUBLE"),
    ("p", "DOUBLE"),
    ("cases", "INTEGER"),
    ("case_carriers", "INTEGER"),
    ("controls", "INTEGER"),
    ("ctrl_carriers", "INTEGER"),
    ("aaf", "DOUBLE"),
    ("mac", "DOUBLE"),
)


def ddl() -> list[str]:
    assoc_cols = ",\n  ".join(f"{c} {t}" for c, t in ASSOC_COLUMNS)
    ann_cols = ",\n  ".join(f"{c} {t}" for c, t in annotation_ddl_columns())
    return [
        "CREATE TABLE meta (key VARCHAR PRIMARY KEY, value JSON)",
        """CREATE TABLE cohort (
  id VARCHAR PRIMARY KEY, label VARCHAR, ord SMALLINT, is_meta BOOLEAN, is_primary BOOLEAN)""",
        """CREATE TABLE trait (
  trait VARCHAR PRIMARY KEY, description VARCHAR, category VARCHAR, category_ord SMALLINT, color VARCHAR)""",
        """CREATE TABLE variant (
  variant_id VARCHAR, gene VARCHAR, chrom VARCHAR, pos BIGINT, ref VARCHAR, alt VARCHAR,
  PRIMARY KEY (variant_id, gene))""",
        f"CREATE TABLE assoc (\n  {assoc_cols})",
        f"CREATE TABLE annotation (\n  {ann_cols},\n  PRIMARY KEY (variant_id, gene))",
        """CREATE TABLE variant_index (
  variant_id VARCHAR, gene VARCHAR, n_traits INTEGER, min_p DOUBLE, top_trait VARCHAR, top_or DOUBLE,
  n_carriers INTEGER, cohorts VARCHAR[],
  PRIMARY KEY (variant_id, gene))""",
        """CREATE TABLE gene_summary (
  gene VARCHAR PRIMARY KEY, chrom VARCHAR, min_pos BIGINT, max_pos BIGINT, n_variants INTEGER,
  min_p DOUBLE, top_variant VARCHAR, top_trait VARCHAR)""",
        "CREATE TABLE rsid_map (rsid VARCHAR, variant_id VARCHAR, gene VARCHAR)",
    ]


def create_schema(con: duckdb.DuckDBPyConnection) -> None:
    for stmt in ddl():
        con.execute(stmt)


def is_v1_dataset(con: duckdb.DuckDBPyConnection) -> bool:
    """True if `con` is open on a database written by this package (vs. the legacy build_db.py layout)."""
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    return {"cohort", "assoc", "meta"} <= tables


# ---------------------------------------------------------------- derived tables

# top_or must be the OR of the top trait's own row, which may be NULL (diverged fit) —
# arg_min(a."or", a.p) would skip the NULL and return the next trait's OR instead.
DERIVE_VARIANT_INDEX = """
INSERT INTO variant_index
SELECT variant_id, gene, n_traits, min_p, top.trait AS top_trait, top."or" AS top_or, n_carriers, cohorts
FROM (
    SELECT a.variant_id, a.gene,
           count(*) FILTER (WHERE a.cohort = $primary)                       AS n_traits,
           min(a.p)  FILTER (WHERE a.cohort = $primary)                      AS min_p,
           arg_min({'trait': a.trait, 'or': a."or"}, a.p)
               FILTER (WHERE a.cohort = $primary)                            AS top,
           max(coalesce(a.case_carriers, 0) + coalesce(a.ctrl_carriers, 0))
               FILTER (WHERE a.cohort = $primary)                            AS n_carriers,
           list_sort(list_distinct(list(a.cohort)))                          AS cohorts
    FROM assoc a
    GROUP BY a.variant_id, a.gene
)
"""

DERIVE_GENE_SUMMARY = """
INSERT INTO gene_summary
SELECT v.gene, min(var.chrom), min(var.pos), max(var.pos), count(*),
       min(v.min_p), arg_min(v.variant_id, v.min_p), arg_min(v.top_trait, v.min_p)
FROM variant_index v
LEFT JOIN variant var ON var.variant_id = v.variant_id AND var.gene = v.gene
GROUP BY v.gene
"""

DERIVE_RSID_MAP = """
INSERT INTO rsid_map
SELECT DISTINCT trim(x) AS rsid, variant_id, gene
FROM (
    SELECT unnest(string_split(replace(existing_variation, '&', ','), ',')) AS x, variant_id, gene
    FROM annotation WHERE existing_variation IS NOT NULL
)
WHERE trim(x) LIKE 'rs%'
"""


def derive_summaries(con: duckdb.DuckDBPyConnection, primary_cohort: str) -> None:
    con.execute("DELETE FROM variant_index")
    con.execute("DELETE FROM gene_summary")
    con.execute("DELETE FROM rsid_map")
    con.execute(DERIVE_VARIANT_INDEX, {"primary": primary_cohort})
    con.execute(DERIVE_GENE_SUMMARY)
    con.execute(DERIVE_RSID_MAP)
