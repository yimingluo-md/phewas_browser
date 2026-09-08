"""Read-only query layer over one dataset. Returns plain dicts/lists (JSON-safe) that are
cohort- and field-agnostic: per-cohort statistics come back as {cohort_id: {stat: value}}
and annotation as {field_name: value}; the API/UI shape them using the manifest.
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path
from typing import Any

import duckdb

from .fields import public_fields, stored_fields
from .manifest import STATISTICS, Manifest
from .schema import is_v1_dataset


class DatasetNotFoundError(KeyError):
    pass


def _json_safe(v: Any) -> Any:
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


class Dataset:
    """One open DuckDB dataset. Thread-safe via a lock (DuckDB connections are not)."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._con = duckdb.connect(str(self.db_path), read_only=True)
        self._lock = threading.Lock()
        if not is_v1_dataset(self._con):
            raise ValueError(f"{self.db_path} is not a phewas_core dataset (schema v1)")
        sidecar = self.db_path.with_name("manifest.json")
        if sidecar.exists():  # the editable copy (name, notes) wins over the one frozen in the database
            self.manifest: Manifest | None = Manifest.load(sidecar)
        else:
            raw = self.q("SELECT value FROM meta WHERE key = 'manifest'")
            self.manifest = Manifest.from_dict(json.loads(raw[0]["value"])) if raw else None
        self.cohort_ids = [r["id"] for r in self.q("SELECT id FROM cohort ORDER BY ord")]
        self.primary = next(
            (r["id"] for r in self.q("SELECT id FROM cohort WHERE is_primary")), self.cohort_ids[0]
        )
        self._ann_cols = [f.name for f in stored_fields()]

    def close(self) -> None:
        self._con.close()

    # ---- raw ------------------------------------------------------------------
    def q(self, sql: str, params: list[Any] | dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._con.execute(sql, params or [])
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        return [{k: _json_safe(v) for k, v in zip(cols, r, strict=True)} for r in rows]

    # ---- metadata ------------------------------------------------------------
    def cohorts(self) -> list[dict[str, Any]]:
        return self.q("SELECT id, label, is_meta, is_primary AS primary FROM cohort ORDER BY ord")

    def fields(self) -> list[dict[str, Any]]:
        return public_fields()

    def meta(self) -> dict[str, Any]:
        genes = self.q("""
            SELECT g.gene, g.chrom, g.min_pos, g.max_pos, g.n_variants, g.min_p, g.top_variant, g.top_trait,
                   t.description AS top_trait_desc
            FROM gene_summary g LEFT JOIN trait t ON t.trait = g.top_trait
            ORDER BY g.gene""")
        stats = self.q(
            """
            SELECT (SELECT count(*) FROM variant_index)       AS n_variants,
                   (SELECT count(*) FROM gene_summary)        AS n_genes,
                   (SELECT count(DISTINCT trait) FROM assoc)  AS n_traits,
                   (SELECT count(*) FROM assoc WHERE cohort = ?) AS n_assoc""",
            [self.primary],
        )[0]
        return {
            "genes": genes,
            "stats": stats,
            "cohorts": self.cohorts(),
            "primary_cohort": self.primary,
            "statistics": self.manifest.statistics if self.manifest else list(STATISTICS),
            "fields": self.fields(),
            "manifest": self.manifest.to_dict() if self.manifest else None,
        }

    # ---- search ------------------------------------------------------------------
    def search(self, term: str, limit: int = 15) -> list[dict[str, Any]]:
        term = term.strip()
        results: list[dict[str, Any]] = []
        for g in self.q(
            "SELECT gene, n_variants FROM gene_summary WHERE upper(gene) LIKE upper(?) || '%' ORDER BY gene LIMIT 10",
            [term],
        ):
            results.append(
                {"type": "gene", "id": g["gene"], "label": f"{g['gene']} ({g['n_variants']} variants)"}
            )
        if term.lower().startswith("rs"):
            for r in self.q(
                """SELECT rsid, variant_id, gene FROM rsid_map WHERE rsid LIKE ? || '%'
                               AND EXISTS (SELECT 1 FROM variant_index v WHERE v.variant_id = rsid_map.variant_id AND v.gene = rsid_map.gene)
                               ORDER BY rsid LIMIT 10""",
                [term.lower()],
            ):
                results.append(
                    {
                        "type": "variant",
                        "id": r["variant_id"],
                        "gene": r["gene"],
                        "label": f"{r['rsid']} — {r['variant_id']} ({r['gene']})",
                    }
                )
        vterm = term[3:] if term.lower().startswith("chr") else term
        if vterm and (vterm[0].isdigit() or vterm[:1].upper() in ("X", "Y", "M")):
            for v in self.q(
                "SELECT variant_id, gene FROM variant_index WHERE variant_id LIKE ? || '%' ORDER BY variant_id LIMIT 10",
                [vterm],
            ):
                results.append(
                    {
                        "type": "variant",
                        "id": v["variant_id"],
                        "gene": v["gene"],
                        "label": f"{v['variant_id']} ({v['gene']})",
                    }
                )
        return results[:limit]

    # ---- gene page ---------------------------------------------------------------
    def gene_page(self, gene: str) -> dict[str, Any]:
        summary = self.q(
            """
            SELECT g.*, t.description AS top_trait_desc
            FROM gene_summary g LEFT JOIN trait t ON t.trait = g.top_trait
            WHERE g.gene = ?""",
            [gene],
        )
        if not summary:
            raise DatasetNotFoundError(f"Gene {gene} not found")
        ann_cols = ", ".join(
            f"a.{c}" for c in self._ann_cols if c not in ("variant_id", "gene", "chrom", "pos", "ref", "alt")
        )
        variants = self.q(
            f"""
            SELECT v.variant_id, v.gene, v.n_traits, v.min_p, v.top_trait, v.top_or, v.n_carriers, v.cohorts,
                   t.description AS top_trait_desc,
                   var.chrom, var.pos, var.ref, var.alt,
                   {ann_cols}
            FROM variant_index v
            LEFT JOIN variant var ON var.variant_id = v.variant_id AND var.gene = v.gene
            LEFT JOIN annotation a ON a.variant_id = v.variant_id AND a.gene = v.gene
            LEFT JOIN trait t ON t.trait = v.top_trait
            WHERE v.gene = ?
            ORDER BY var.pos NULLS LAST, v.variant_id""",
            [gene],
        )
        return {"summary": summary[0], "variants": variants}

    # ---- variant page ----------------------------------------------------------
    def genes_for_variant(self, variant_id: str) -> list[str]:
        return [
            r["gene"]
            for r in self.q("SELECT gene FROM variant_index WHERE variant_id = ? ORDER BY gene", [variant_id])
        ]

    def variant_page(self, variant_id: str, gene: str | None = None) -> dict[str, Any]:
        if variant_id.lower().startswith("chr"):
            variant_id = variant_id[3:]
        genes = self.genes_for_variant(variant_id)
        if gene is None:
            if not genes:
                raise DatasetNotFoundError(f"Variant {variant_id} not found")
            gene = genes[0]
        ann = self.q("SELECT * FROM annotation WHERE variant_id = ? AND gene = ?", [variant_id, gene])
        var = self.q("SELECT * FROM variant WHERE variant_id = ? AND gene = ?", [variant_id, gene])
        stat_cols = ", ".join(f'a."{s}"' for s in STATISTICS)
        rows = self.q(
            f"""
            SELECT a.trait, t.description, t.category, t.category_ord, t.color, a.cohort, {stat_cols}
            FROM assoc a LEFT JOIN trait t ON t.trait = a.trait
            WHERE a.variant_id = ? AND a.gene = ?
            ORDER BY t.category_ord NULLS LAST, a.trait, a.cohort""",
            [variant_id, gene],
        )
        if not rows and not ann:
            raise DatasetNotFoundError(f"Variant {variant_id} ({gene}) not found")
        # pivot long rows -> one entry per trait with {cohort: {stat: value}}
        assoc: list[dict[str, Any]] = []
        by_trait: dict[str, dict[str, Any]] = {}
        for r in rows:
            e = by_trait.get(r["trait"])
            if e is None:
                e = {
                    "trait": r["trait"],
                    "description": r["description"],
                    "category": r["category"],
                    "category_ord": r["category_ord"],
                    "color": r["color"],
                    "cohorts": {},
                }
                by_trait[r["trait"]] = e
                assoc.append(e)
            e["cohorts"][r["cohort"]] = {s: r[s] for s in STATISTICS}
        return {
            "variant_id": variant_id,
            "gene": gene,
            "genes_for_variant": genes,
            "variant": var[0] if var else None,
            "annotation": ann[0] if ann else None,
            "primary_cohort": self.primary,
            "cohort_ids": self.cohort_ids,
            "associations": assoc,
        }
