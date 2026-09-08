"""Annotation import: VEP tab-separated output -> the `annotation` table, driven by fields.py.

Transcript choice per (variant, gene): MANE Select, else VEP canonical, else the first
transcript by Feature id. '-' and '' are missing. dbNSFP per-transcript values are
collapsed by the multi_max / multi_pred macros. Variant ids are normalised to the
sumstats form (no 'chr' prefix).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from ._db import count
from .fields import vep_macros, vep_select_list

VEP_ID_COL = "#Uploaded_variation"
VEP_GENE_COL = "SYMBOL"


def vep_header(con: duckdb.DuckDBPyConnection, path: Path) -> list[str]:
    rows = con.execute(
        "DESCRIBE SELECT * FROM read_csv(?, delim='\t', header=true, all_varchar=true, quote='', sample_size=100)",
        [str(path)],
    ).fetchall()
    return [r[0] for r in rows]


def import_vep(con: duckdb.DuckDBPyConnection, path: Path, strip_chr_prefix: bool = True) -> int:
    """Load `path` into the (empty) annotation table. Returns the number of rows written."""
    header = vep_header(con, path)
    for col in (VEP_ID_COL, VEP_GENE_COL, "Feature"):
        if col not in header:
            raise ValueError(f"annotation file lacks required VEP column {col!r}")
    for m in vep_macros():
        con.execute(m)
    con.execute("DROP TABLE IF EXISTS raw_ann")
    con.execute(
        "CREATE TEMP TABLE raw_ann AS SELECT * FROM read_csv(?, delim='\t', header=true, all_varchar=true, quote='', sample_size=-1)",
        [str(path)],
    )
    has_mane = "MANE_SELECT" in header
    has_canon = "CANONICAL" in header
    order = []
    if has_mane:
        order.append("(NULLIF(MANE_SELECT, '-') IS NOT NULL) DESC")
    if has_canon:
        order.append("(CANONICAL = 'YES') DESC")
    order.append("Feature")
    name_expr = f"regexp_replace(\"{VEP_ID_COL}\", '^chr', '')" if strip_chr_prefix else f'"{VEP_ID_COL}"'
    # DuckDB identifiers are case-insensitive: VEP's own "Gene" (Ensembl id) would shadow our
    # `gene` alias (= SYMBOL), so raw columns colliding with structural names are excluded.
    structural = {"variant_id", "gene", "chrom", "pos", "ref", "alt", "rn"}
    collide = [c for c in header if c.lower() in structural]
    exclude = f"EXCLUDE ({', '.join(chr(34) + c + chr(34) for c in collide)})" if collide else ""
    inner, outer = vep_select_list(set(header))
    con.execute(f"""
        INSERT INTO annotation
        WITH ranked AS (
            SELECT * {exclude}, {name_expr} AS variant_id,
                   row_number() OVER (PARTITION BY "{VEP_ID_COL}", "{VEP_GENE_COL}" ORDER BY {", ".join(order)}) AS rn
            FROM raw_ann
            -- rows without a gene symbol (intergenic / regulatory features) or without a variant id
            -- cannot join any association and would violate the (variant_id, gene) key
            WHERE NULLIF(NULLIF("{VEP_GENE_COL}", '-'), '') IS NOT NULL
              AND NULLIF(NULLIF("{VEP_ID_COL}", '-'), '') IS NOT NULL
        ),
        picked AS (
            SELECT *,
                   "{VEP_GENE_COL}"                              AS gene,
                   string_split(variant_id, ':')[1]              AS chrom,
                   TRY_CAST(string_split(variant_id, ':')[2] AS BIGINT) AS pos,
                   string_split(variant_id, ':')[3]              AS ref,
                   string_split(variant_id, ':')[4]              AS alt
            FROM ranked WHERE rn = 1
        ),
        clean AS (
            SELECT
    {inner}
            FROM picked
        )
        SELECT
    {outer}
        FROM clean
    """)
    con.execute("DROP TABLE raw_ann")
    return count(con, "SELECT count(*) FROM annotation")
