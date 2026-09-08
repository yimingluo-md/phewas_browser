#!/usr/bin/env python3
"""Compare a phewas_core dataset with a legacy build_db.py database, value for value.

    uv run python scripts/compare_with_legacy.py data/phewas.duckdb [dataset-id-or-dir] [--sample 300]

Checks gene_summary, variant_index, annotation (every field), rsid_map completely, and
the long `assoc` table against the wide one for a random sample of variants (all traits,
all cohorts). Prints one line per check; exit status 1 if anything differs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "phewas_core"))
from phewas_core.fields import stored_fields
from phewas_core.registry import Library

TOL = 1e-9


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("legacy_db")
    ap.add_argument("dataset", nargs="?", help="dataset id/prefix/dir (default: current)")
    ap.add_argument("--sample", type=int, default=300, help="variants to compare in assoc")
    ap.add_argument("--home")
    a = ap.parse_args()

    lib = Library(Path(a.home) if a.home else None)
    ref = lib.get(a.dataset) if a.dataset else lib.current()
    if ref is None:
        print("no dataset")
        return 2
    con = duckdb.connect()
    con.execute("SET memory_limit='2GB'")
    con.execute(f"ATTACH '{a.legacy_db}' AS L (READ_ONLY)")
    con.execute(f"ATTACH '{ref.db_path}' AS N (READ_ONLY)")
    primary = con.execute("SELECT id FROM N.cohort WHERE is_primary").fetchone()[0]
    print(f"legacy: {a.legacy_db}\nnew:    {ref.db_path} (primary cohort {primary})\n")
    fails = 0

    def check(label: str, n_diff: int, detail: str = "") -> None:
        nonlocal fails
        status = "OK  " if n_diff == 0 else "DIFF"
        fails += n_diff != 0
        print(
            f"{status} {label}{'' if n_diff == 0 else f': {n_diff} differences'}{(' — ' + detail) if detail else ''}"
        )

    def num_diff(x: str, y: str) -> str:
        # legacy stores Inf/NaN (diverged fits) where the new schema stores NULL: both count as missing
        lx = f"(CASE WHEN isfinite({x}) THEN {x} END)"
        return f"NOT ((({lx}) IS NULL AND ({y}) IS NULL) OR abs(({lx}) - ({y})) <= {TOL} * greatest(1, abs({lx})))"

    # ---- counts -------------------------------------------------------
    # legacy keeps VEP rows without a gene symbol (never joined to anything); the new schema drops them
    con.execute("CREATE TEMP VIEW L_rsid AS SELECT * FROM L.rsid_map WHERE gene IS NOT NULL AND gene <> '-'")
    for t_l, t_n in [
        ("gene_summary", "gene_summary"),
        ("variant_index", "variant_index"),
        ("L_rsid", "rsid_map"),
    ]:
        nl = con.execute(f"SELECT count(*) FROM {'L.' if not t_l.startswith('L_') else ''}{t_l}").fetchone()[
            0
        ]
        nn = con.execute(f"SELECT count(*) FROM N.{t_n}").fetchone()[0]
        check(f"{t_n} row count", int(nl != nn), f"legacy {nl:,} vs new {nn:,}")
    nl = con.execute("SELECT count(*) FROM L.assoc").fetchone()[0]
    nn = con.execute("SELECT count(*) FROM N.assoc WHERE cohort = ?", [primary]).fetchone()[0]
    check("assoc (primary cohort) row count", int(nl != nn), f"legacy {nl:,} vs new {nn:,}")

    # ---- gene_summary -------------------------------------------------------
    d = con.execute(f"""
        SELECT count(*) FROM L.gene_summary l FULL JOIN N.gene_summary n ON n.gene = l.gene
        WHERE l.gene IS NULL OR n.gene IS NULL
           OR l.chrom IS DISTINCT FROM n.chrom OR l.min_pos IS DISTINCT FROM n.min_pos
           OR l.max_pos IS DISTINCT FROM n.max_pos OR l.n_variants <> n.n_variants
           OR l.top_variant IS DISTINCT FROM n.top_variant OR l.top_trait IS DISTINCT FROM n.top_trait
           OR {num_diff("l.min_p", "n.min_p")}""").fetchone()[0]
    check("gene_summary values", d)

    # ---- variant_index ----------------------------------------------------------
    d = con.execute(f"""
        SELECT count(*) FROM L.variant_index l FULL JOIN N.variant_index n ON n.variant_id = l.name AND n.gene = l.gene
        WHERE l.name IS NULL OR n.variant_id IS NULL
           OR l.n_traits <> n.n_traits OR l.top_trait IS DISTINCT FROM n.top_trait
           OR l.n_carriers IS DISTINCT FROM n.n_carriers
           OR {num_diff("l.min_p", "n.min_p")} OR {num_diff("l.top_or", "n.top_or")}""").fetchone()[0]
    check("variant_index values (n_traits, min_p, top_trait, top_or, n_carriers)", d)

    # ---- annotation --------------------------------------------------------------
    lcols = {r[0] for r in con.execute("DESCRIBE L.annotation").fetchall()}
    conds = []
    for f in stored_fields():
        if f.name in ("variant_id", "gene"):
            continue
        lname = "name" if f.name == "variant_id" else f.name
        if lname not in lcols:
            print(f"     (annotation.{f.name}: not in legacy table, skipped)")
            continue
        conds.append(
            num_diff(f"l.{lname}", f"n.{f.name}")
            if f.type == "num"
            else f"l.{lname} IS DISTINCT FROM n.{f.name}"
        )
    d = con.execute(f"""
        SELECT count(*) FROM (SELECT * FROM L.annotation WHERE gene IS NOT NULL AND gene <> '-') l
        FULL JOIN N.annotation n ON n.variant_id = l.name AND n.gene = l.gene
        WHERE l.name IS NULL OR n.variant_id IS NULL OR {" OR ".join(conds)}""").fetchone()[0]
    check(f"annotation values ({len(conds)} fields, all variant-gene pairs)", d)

    # ---- rsid_map -----------------------------------------------------------------------
    d = con.execute("""SELECT count(*) FROM L_rsid l FULL JOIN N.rsid_map n
                       ON n.rsid = l.rsid AND n.variant_id = l.name AND n.gene = l.gene
                       WHERE l.rsid IS NULL OR n.rsid IS NULL""").fetchone()[0]
    check("rsid_map", d)

    # ---- assoc sample ---------------------------------------------------------------------
    con.execute(f"""CREATE TEMP TABLE sample AS
                    SELECT name, gene FROM L.variant_index ORDER BY hash(name || gene) LIMIT {a.sample}""")
    cohorts = con.execute("SELECT id, is_meta FROM N.cohort ORDER BY ord").fetchall()
    stats = [
        ("or", "or"),
        ("p", "p"),
        ("cases", "cases"),
        ("casecarr", "case_carriers"),
        ("controls", "controls"),
        ("ctrlcarr", "ctrl_carriers"),
    ]
    for cid, is_meta in cohorts:
        suf = "meta" if is_meta else cid.lower()
        conds = []
        for ls, ns in stats:
            conds.append(num_diff(f"l.{ls}_{suf}", f'n."{ns}"'))
        # legacy: cohort absent == all its stat columns NULL; new: no row
        d = con.execute(f"""
            WITH l AS (SELECT a.* FROM L.assoc a JOIN sample s ON s.name = a.name AND s.gene = a.gene),
                 n AS (SELECT a.* FROM N.assoc a JOIN sample s ON s.name = a.variant_id AND s.gene = a.gene WHERE a.cohort = '{cid}')
            SELECT count(*) FROM l FULL JOIN n ON n.variant_id = l.name AND n.gene = l.gene AND n.trait = l.trait
            WHERE (l.name IS NULL)
               OR (n.variant_id IS NULL AND NOT (l.or_{suf} IS NULL AND l.p_{suf} IS NULL AND l.cases_{suf} IS NULL))
               OR (n.variant_id IS NOT NULL AND ({" OR ".join(conds)}))""").fetchone()[0]
        check(f"assoc {cid:5} ({a.sample} sampled variants, all traits)", d)

    print("\nRESULT:", "identical" if fails == 0 else f"{fails} check(s) differ")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
