#!/usr/bin/env python3
"""Local PheWAS browser for IEI variant-level AoU+UKBB meta-analysis.

Run:  ./launch.sh
Then open http://localhost:8555
"""
import math
import os
import threading

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = os.path.dirname(os.path.abspath(__file__))
# IEI_PHEWAS_DB lets tests and future launchers point the server at another database.
DB = os.environ.get("IEI_PHEWAS_DB") or os.path.join(BASE, "data", "phewas.duckdb")

app = FastAPI(title="IEI PheWAS Browser")

_con = duckdb.connect(DB, read_only=True)
_lock = threading.Lock()


def q(sql, params=None):
    """Run a query, return list-of-dicts with JSON-safe floats."""
    with _lock:
        cur = _con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    out = []
    for r in rows:
        d = {}
        for k, v in zip(cols, r, strict=True):
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                v = None
            d[k] = v
        out.append(d)
    return out


# A launcher-specific health check prevents an unrelated service on the same
# port from being mistaken for this browser.
@app.get("/api/health")
def health():
    return {"application": "IEI PheWAS Browser", "status": "ok"}


# ---------------------------------------------------------------- meta
@app.get("/api/meta")
def meta():
    genes = q("""
        SELECT gene, chrom, min_pos, max_pos, n_variants, min_p, top_variant, top_trait,
               p.description AS top_trait_desc
        FROM gene_summary g
        LEFT JOIN phecode p ON p.phecode = g.top_trait
        ORDER BY gene
    """)
    stats = q("""
        SELECT (SELECT count(*) FROM variant_index)          AS n_variants,
               (SELECT count(*) FROM gene_summary)           AS n_genes,
               (SELECT count(DISTINCT trait) FROM assoc)     AS n_traits,
               (SELECT count(*) FROM assoc)                  AS n_assoc
    """)[0]
    return {"genes": genes, "stats": stats}


# ---------------------------------------------------------------- search
@app.get("/api/search")
def search(term: str = Query(..., min_length=1)):
    term = term.strip()
    results = []

    gene_hits = q(
        "SELECT gene, n_variants FROM gene_summary WHERE upper(gene) LIKE upper(?) || '%' ORDER BY gene LIMIT 10",
        [term])
    results += [{"type": "gene", "id": g["gene"], "label": f"{g['gene']} ({g['n_variants']} variants)"}
                for g in gene_hits]

    if term.lower().startswith("rs"):
        rs_hits = q(
            "SELECT rsid, name, gene FROM rsid_map WHERE rsid LIKE ? || '%' "
            "AND EXISTS (SELECT 1 FROM variant_index v WHERE v.name=rsid_map.name AND v.gene=rsid_map.gene) "
            "ORDER BY rsid LIMIT 10", [term.lower()])
        results += [{"type": "variant", "id": r["name"], "gene": r["gene"],
                     "label": f"{r['rsid']} — {r['name']} ({r['gene']})"} for r in rs_hits]

    vterm = term[3:] if term.lower().startswith("chr") else term
    if (vterm and vterm[0].isdigit()) or vterm[:1].upper() in ("X", "Y"):
        v_hits = q(
            "SELECT name, gene FROM variant_index WHERE name LIKE ? || '%' ORDER BY name LIMIT 10",
            [vterm])
        results += [{"type": "variant", "id": v["name"], "gene": v["gene"],
                     "label": f"{v['name']} ({v['gene']})"} for v in v_hits]

    return {"results": results[:15]}


# ---------------------------------------------------------------- gene page
@app.get("/api/gene/{gene}")
def gene_page(gene: str):
    summary = q("""
        SELECT g.*, p.description AS top_trait_desc
        FROM gene_summary g LEFT JOIN phecode p ON p.phecode = g.top_trait
        WHERE g.gene = ?
    """, [gene])
    if not summary:
        raise HTTPException(404, f"Gene {gene} not found")
    variants = q("""
        SELECT
            v.name, v.n_traits, v.min_p, v.top_trait, v.top_or, v.n_carriers, v.source_any,
            p.description AS top_trait_desc,
            ann.pos, ann.ref, ann.alt, ann.consequence, ann.impact, ann.hgvsc, ann.hgvsp,
            ann.existing_variation, ann.clin_sig, ann.clinvar_clnsig,
            ann.gnomade_af, ann.gnomadg_af, ann.max_af,
            ann.cadd_phred, ann.revel_score, ann.alphamissense_pred, ann.spliceai_max_ds,
            ann.lof, ann.logofunc_prediction, ann.promoterai_score
        FROM variant_index v
        LEFT JOIN annotation ann ON ann.name = v.name AND ann.gene = v.gene
        LEFT JOIN phecode p ON p.phecode = v.top_trait
        WHERE v.gene = ?
        ORDER BY ann.pos NULLS LAST, v.name
    """, [gene])
    return {"summary": summary[0], "variants": variants}


# ---------------------------------------------------------------- variant page
@app.get("/api/variant/{name}")
def variant_page(name: str, gene: str = Query(None)):
    name = name.replace("chr", "") if name.lower().startswith("chr") else name
    if gene is None:
        hit = q("SELECT gene FROM variant_index WHERE name = ? LIMIT 1", [name])
        if not hit:
            raise HTTPException(404, f"Variant {name} not found")
        gene = hit[0]["gene"]

    ann = q("SELECT * FROM annotation WHERE name = ? AND gene = ?", [name, gene])
    genes_for_variant = q(
        "SELECT gene FROM variant_index WHERE name = ? ORDER BY gene", [name])

    assoc = q("""
        SELECT
            a.trait, p.description, p.category, p.groupnum, p.color,
            a.source,
            a.or_meta, a.p_meta,
            a.cases_meta, a.casecarr_meta, a.controls_meta, a.ctrlcarr_meta,
            a.or_aou, a.p_aou,
            a.cases_aou, a.casecarr_aou, a.controls_aou, a.ctrlcarr_aou,
            a.or_ukbb, a.p_ukbb,
            a.cases_ukbb, a.casecarr_ukbb, a.controls_ukbb, a.ctrlcarr_ukbb
        FROM assoc a
        JOIN phecode p ON p.phecode = a.trait
        WHERE a.name = ? AND a.gene = ?
        ORDER BY p.groupnum, a.trait
    """, [name, gene])
    if not assoc and not ann:
        raise HTTPException(404, f"Variant {name} ({gene}) not found")
    return {
        "name": name,
        "gene": gene,
        "genes_for_variant": [g["gene"] for g in genes_for_variant],
        "annotation": ann[0] if ann else None,
        "associations": assoc,
    }


# ---------------------------------------------------------------- static frontend
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))
