"""Adapter: phewas_core.query results -> the JSON shapes the Phase-0 frontend (static/app.js)
expects, i.e. flat per-cohort columns `or_meta, p_aou, ...`, `name`, `groupnum`, `source`.

Temporary: removed in Phase 2 when the frontend renders from the manifest. Kept separate so the
same API tests can run against both the legacy build_db.py database and a phewas_core dataset.
"""

from __future__ import annotations

from typing import Any

from .query import Dataset

_LEGACY_STATS = {
    "or": "or",
    "p": "p",
    "cases": "cases",
    "case_carriers": "casecarr",
    "controls": "controls",
    "ctrl_carriers": "ctrlcarr",
}


def _suffix(cohort: dict[str, Any]) -> str:
    return "meta" if cohort["is_meta"] else str(cohort["id"]).lower()


def _source(cohort_ids: list[str], present: set[str], cohorts: list[dict[str, Any]]) -> str:
    non_meta = [c["id"] for c in cohorts if not c["is_meta"] and c["id"] in present]
    return "+".join(non_meta) if non_meta else "+".join(sorted(present))


def meta(ds: Dataset) -> dict[str, Any]:
    m = ds.meta()
    return {"genes": m["genes"], "stats": m["stats"]}


def search(ds: Dataset, term: str) -> dict[str, Any]:
    return {"results": ds.search(term)}


def gene_page(ds: Dataset, gene: str) -> dict[str, Any]:
    g = ds.gene_page(gene)
    cohorts = ds.cohorts()
    for v in g["variants"]:
        v["name"] = v["variant_id"]
        v["source_any"] = _source(ds.cohort_ids, set(v.get("cohorts") or []), cohorts)
    return g


def variant_page(ds: Dataset, variant_id: str, gene: str | None) -> dict[str, Any]:
    v = ds.variant_page(variant_id, gene)
    cohorts = ds.cohorts()
    suffixes = {c["id"]: _suffix(c) for c in cohorts}
    flat = []
    for a in v["associations"]:
        row: dict[str, Any] = {
            "trait": a["trait"],
            "description": a["description"],
            "category": a["category"],
            "groupnum": a["category_ord"],
            "color": a["color"],
            "source": _source(ds.cohort_ids, set(a["cohorts"]), cohorts),
        }
        for cid, suf in suffixes.items():
            stats = a["cohorts"].get(cid) or {}
            for stat, legacy in _LEGACY_STATS.items():
                row[f"{legacy}_{suf}"] = stats.get(stat)
        flat.append(row)
    ann = v["annotation"]
    if ann is not None:
        ann = dict(ann)
        ann["name"] = ann["variant_id"]
    return {
        "name": v["variant_id"],
        "gene": v["gene"],
        "genes_for_variant": v["genes_for_variant"],
        "annotation": ann,
        "associations": flat,
    }
