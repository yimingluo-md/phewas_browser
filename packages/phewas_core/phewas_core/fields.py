"""The annotation field registry — the single place an annotation column is defined.

Each Field says how it is named and typed in the `annotation` table, how the UI should
label/group/format it, and how each annotation *source profile* (today: 'vep-tsv')
computes it from raw columns. The importer generates its SQL from this list, the API
sends the list to the frontend, and the frontend renders cards, table columns, filters
and CSV headers from it. Adding a field means adding one entry here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

FieldType = Literal["str", "num", "int", "bool"]

# Transforms applied to a raw VEP column (all treat '-' and '' as missing):
#   str        keep text
#   num        TRY_CAST to DOUBLE
#   int        TRY_CAST to BIGINT
#   bool_yes   column = 'YES'
#   multi_max  '0.1&.&0.9' -> 0.9      (dbNSFP per-transcript numeric values)
#   multi_pred 'T&.&D'     -> 'T/D'    (dbNSFP per-transcript labels, distinct, no '.')
Transform = Literal["str", "num", "int", "bool_yes", "multi_max", "multi_pred"]


@dataclass(frozen=True)
class VepSource:
    cols: tuple[str, ...]  # first non-missing wins (e.g. CADD_PHRED, then CADD_phred)
    transform: Transform = "str"


@dataclass(frozen=True)
class Field:
    name: str
    type: FieldType
    label: str
    group: str
    fmt: str = ""  # hint for the frontend formatter: p, or, af, score1, score2, score3, int, text
    vep: VepSource | None = None
    derived: str | None = None  # SQL over other (possibly hidden) fields, applied after sources
    hidden: bool = False  # intermediate only; not stored
    table: bool = False  # shown as a column of the gene-page variant table
    filter: Literal["", "min", "max", "eq", "in", "text"] = ""
    structural: bool = False  # identity columns (variant_id, gene, ...) rather than annotation
    aliases: tuple[str, ...] = field(default_factory=tuple)  # legacy names accepted in queries

    @property
    def sql_type(self) -> str:
        return {"str": "VARCHAR", "num": "DOUBLE", "int": "BIGINT", "bool": "BOOLEAN"}[self.type]


def _v(*cols: str, t: Transform = "str") -> VepSource:
    return VepSource(cols=tuple(cols), transform=t)


_POPS = ("afr", "amr", "eas", "nfe", "sas")

FIELDS: tuple[Field, ...] = (
    # ---- identity (structural) ----------------------------------------
    Field("variant_id", "str", "Variant", "Variant", structural=True),
    Field("gene", "str", "Gene", "Variant", structural=True),
    Field("chrom", "str", "Chromosome", "Variant", structural=True),
    Field("pos", "int", "Position", "Variant", fmt="int", structural=True, table=True),
    Field("ref", "str", "Ref", "Variant", structural=True),
    Field("alt", "str", "Alt", "Variant", structural=True),
    Field("transcript", "str", "Transcript", "Variant", vep=_v("Feature")),
    Field("mane_select", "str", "MANE Select", "Variant", vep=_v("MANE_SELECT")),
    Field("canonical", "bool", "Canonical transcript", "Variant", vep=_v("CANONICAL", t="bool_yes")),
    # ---- consequence --------------------------------------------------
    Field("consequence", "str", "Consequence", "Variant", vep=_v("Consequence"), table=True, filter="in"),
    Field("impact", "str", "IMPACT", "Variant", vep=_v("IMPACT"), table=True, filter="eq"),
    Field("exon", "str", "Exon", "Variant", vep=_v("EXON")),
    Field("intron", "str", "Intron", "Variant", vep=_v("INTRON")),
    Field("hgvsc", "str", "HGVSc", "Variant", vep=_v("HGVSc"), table=True, filter="text"),
    Field("hgvsp", "str", "HGVSp", "Variant", vep=_v("HGVSp"), table=True, filter="text"),
    Field(
        "existing_variation",
        "str",
        "Existing variation",
        "Variant",
        vep=_v("Existing_variation"),
        table=True,
        filter="text",
    ),
    Field("clin_sig", "str", "Clinical significance (VEP)", "ClinVar", vep=_v("CLIN_SIG")),
    # ---- population frequency ------------------------------------------
    Field(
        "gnomade_af",
        "num",
        "gnomAD exomes AF",
        "Population frequency",
        fmt="af",
        vep=_v("gnomADe_AF", t="num"),
        table=True,
    ),
    Field(
        "gnomadg_af",
        "num",
        "gnomAD genomes AF",
        "Population frequency",
        fmt="af",
        vep=_v("gnomADg_AF", t="num"),
        table=True,
    ),
    Field(
        "max_af",
        "num",
        "MAX_AF (all sources)",
        "Population frequency",
        fmt="af",
        vep=_v("MAX_AF", t="num"),
        table=True,
        filter="max",
    ),
    Field("max_af_pops", "str", "MAX_AF populations", "Population frequency", vep=_v("MAX_AF_POPS")),
    *[
        Field(
            f"e_{p}",
            "num",
            f"gnomADe {p.upper()}",
            "Population frequency",
            vep=_v(f"gnomADe_{p.upper()}_AF", t="num"),
            hidden=True,
        )
        for p in _POPS
    ],
    *[
        Field(
            f"g_{p}",
            "num",
            f"gnomADg {p.upper()}",
            "Population frequency",
            vep=_v(f"gnomADg_{p.upper()}_AF", t="num"),
            hidden=True,
        )
        for p in _POPS
    ],
    Field(
        "gnomad_popmax_af",
        "num",
        "gnomAD popmax AF",
        "Population frequency",
        fmt="af",
        derived="greatest(" + ", ".join([f"e_{p}" for p in _POPS] + [f"g_{p}" for p in _POPS]) + ")",
    ),
    Field(
        "gnomad_popmax_pop",
        "str",
        "gnomAD popmax population",
        "Population frequency",
        derived="CASE greatest("
        + ", ".join([f"e_{p}" for p in _POPS] + [f"g_{p}" for p in _POPS])
        + ") "
        + " ".join(f"WHEN e_{p} THEN '{p.upper()} (exomes)'" for p in _POPS)
        + " "
        + " ".join(f"WHEN g_{p} THEN '{p.upper()} (genomes)'" for p in _POPS)
        + " END",
    ),
    # ---- deleteriousness ------------------------------------------------
    Field(
        "cadd_phred",
        "num",
        "CADD (phred)",
        "Deleteriousness",
        fmt="score1",
        vep=_v("CADD_PHRED", "CADD_phred", t="num"),
        table=True,
        filter="min",
    ),
    Field(
        "revel_score",
        "num",
        "REVEL",
        "Deleteriousness",
        fmt="score3",
        vep=_v("REVEL_score", t="multi_max"),
        table=True,
    ),
    Field(
        "alphamissense_pred",
        "str",
        "AlphaMissense",
        "Deleteriousness",
        vep=_v("AlphaMissense_pred", t="multi_pred"),
        table=True,
    ),
    Field(
        "alphamissense_score",
        "num",
        "AlphaMissense score",
        "Deleteriousness",
        fmt="score3",
        vep=_v("AlphaMissense_score", t="multi_max"),
    ),
    Field("metarnn_pred", "str", "MetaRNN", "Deleteriousness", vep=_v("MetaRNN_pred", t="multi_pred")),
    Field(
        "metarnn_score",
        "num",
        "MetaRNN score",
        "Deleteriousness",
        fmt="score3",
        vep=_v("MetaRNN_score", t="multi_max"),
    ),
    Field("primateai_pred", "str", "PrimateAI", "Deleteriousness", vep=_v("PrimateAI_pred", t="multi_pred")),
    Field("sift_pred", "str", "SIFT", "Deleteriousness", vep=_v("SIFT_pred", t="multi_pred")),
    Field("polyphen", "str", "PolyPhen", "Deleteriousness", vep=_v("PolyPhen")),
    Field(
        "phylop100way",
        "num",
        "phyloP (100way)",
        "Deleteriousness",
        fmt="score2",
        vep=_v("phyloP100way_vertebrate", t="multi_max"),
    ),
    # ---- ClinVar ----------------------------------------------------------
    Field("clinvar_clnsig", "str", "ClinVar significance", "ClinVar", vep=_v("ClinVar_CLNSIG"), table=True),
    Field("clinvar_clnsigconf", "str", "ClinVar conflicting detail", "ClinVar", vep=_v("ClinVar_CLNSIGCONF")),
    Field("clinvar_clnrevstat", "str", "ClinVar review status", "ClinVar", vep=_v("ClinVar_CLNREVSTAT")),
    Field("clinvar_clndn", "str", "ClinVar disease", "ClinVar", vep=_v("ClinVar_CLNDN")),
    # ---- splicing & LoF -----------------------------------------------------
    Field(
        "spliceai_ds_ag",
        "num",
        "SpliceAI DS AG",
        "Splicing & LoF",
        fmt="score2",
        vep=_v("SpliceAI_pred_DS_AG", t="num"),
    ),
    Field(
        "spliceai_ds_al",
        "num",
        "SpliceAI DS AL",
        "Splicing & LoF",
        fmt="score2",
        vep=_v("SpliceAI_pred_DS_AL", t="num"),
    ),
    Field(
        "spliceai_ds_dg",
        "num",
        "SpliceAI DS DG",
        "Splicing & LoF",
        fmt="score2",
        vep=_v("SpliceAI_pred_DS_DG", t="num"),
    ),
    Field(
        "spliceai_ds_dl",
        "num",
        "SpliceAI DS DL",
        "Splicing & LoF",
        fmt="score2",
        vep=_v("SpliceAI_pred_DS_DL", t="num"),
    ),
    Field(
        "spliceai_max_ds",
        "num",
        "SpliceAI max DS",
        "Splicing & LoF",
        fmt="score2",
        vep=_v("SpliceAI_max_DS", t="num"),
        table=True,
    ),
    Field("spliceai_source", "str", "SpliceAI source", "Splicing & LoF", vep=_v("SpliceAI_source")),
    Field(
        "rule_50bp_recomputed",
        "str",
        "50 bp rule (recomputed)",
        "Splicing & LoF",
        vep=_v("50_BP_RULE_recomputed"),
    ),
    Field("lof", "str", "LOFTEE", "Splicing & LoF", vep=_v("LoF"), table=True, filter="eq"),
    Field("lof_filter", "str", "LoF filter", "Splicing & LoF", vep=_v("LoF_filter")),
    Field("lof_flags", "str", "LoF flags", "Splicing & LoF", vep=_v("LoF_flags")),
    Field("lof_info", "str", "LoF info", "Splicing & LoF", vep=_v("LoF_info")),
    # ---- LoGoFunc & regulatory -----------------------------------------------
    Field(
        "logofunc_gof",
        "num",
        "LoGoFunc P(GOF)",
        "LoGoFunc & regulatory",
        fmt="score2",
        vep=_v("LoGoFunc_GOF", t="num"),
    ),
    Field(
        "logofunc_lof",
        "num",
        "LoGoFunc P(LOF)",
        "LoGoFunc & regulatory",
        fmt="score2",
        vep=_v("LoGoFunc_LOF", t="num"),
    ),
    Field(
        "logofunc_neutral",
        "num",
        "LoGoFunc P(neutral)",
        "LoGoFunc & regulatory",
        fmt="score2",
        vep=_v("LoGoFunc_neutral", t="num"),
    ),
    Field(
        "logofunc_prediction",
        "str",
        "LoGoFunc prediction",
        "LoGoFunc & regulatory",
        vep=_v("LoGoFunc_prediction"),
        table=True,
    ),
    Field(
        "promoterai_score",
        "num",
        "PromoterAI",
        "LoGoFunc & regulatory",
        fmt="score3",
        vep=_v("PromoterAI_score", t="num"),
        table=True,
    ),
)

BY_NAME: dict[str, Field] = {f.name: f for f in FIELDS}


def stored_fields() -> list[Field]:
    """Fields that are columns of the `annotation` table, in order."""
    return [f for f in FIELDS if not f.hidden]


def annotation_ddl_columns() -> list[tuple[str, str]]:
    return [(f.name, f.sql_type) for f in stored_fields()]


def public_fields() -> list[dict[str, object]]:
    """What the API hands to the frontend."""
    return [
        {
            "name": f.name,
            "type": f.type,
            "label": f.label,
            "group": f.group,
            "fmt": f.fmt,
            "table": f.table,
            "filter": f.filter,
            "structural": f.structural,
        }
        for f in stored_fields()
    ]


# ---------------------------------------------------------------- VEP SQL generation

_MACROS = [
    # dbNSFP fields carry '&'-joined per-transcript values ("T&.&.&T")
    """CREATE OR REPLACE TEMP MACRO multi_pred(x) AS NULLIF(array_to_string(
        list_distinct(list_filter(string_split(x, '&'), y -> y NOT IN ('.', ''))), '/'), '')""",
    """CREATE OR REPLACE TEMP MACRO multi_max(x) AS list_max(
        list_transform(
            list_filter(string_split(x, '&'), y -> TRY_CAST(y AS DOUBLE) IS NOT NULL),
            y -> CAST(y AS DOUBLE)))""",
]


def vep_macros() -> list[str]:
    return list(_MACROS)


def _raw(col: str) -> str:
    return f"NULLIF(NULLIF(\"{col}\", '-'), '')"


def vep_expression(f: Field, header: set[str]) -> str:
    """SQL expression computing field `f` from the raw VEP columns present in `header`."""
    assert f.vep is not None
    cols = [c for c in f.vep.cols if c in header]
    if not cols:
        return f"NULL::{f.sql_type}"
    raw = _raw(cols[0]) if len(cols) == 1 else "COALESCE(" + ", ".join(_raw(c) for c in cols) + ")"
    t = f.vep.transform
    if t == "str":
        return raw
    if t == "num":
        return f"TRY_CAST({raw} AS DOUBLE)"
    if t == "int":
        return f"TRY_CAST({raw} AS BIGINT)"
    if t == "bool_yes":
        return f"({raw} = 'YES')"
    if t == "multi_max":
        return f"multi_max({raw})"
    if t == "multi_pred":
        return f"multi_pred({raw})"
    raise ValueError(t)


def vep_select_list(header: set[str]) -> tuple[str, str]:
    """Return (inner_select, outer_select): the inner computes sourced + hidden fields,
    the outer adds derived fields and drops hidden ones. Structural fields are expected
    to be provided by the caller's CTE as variant_id, gene, chrom, pos, ref, alt."""
    inner, outer = [], []
    for f in FIELDS:
        if f.structural:
            inner.append(f.name)
            outer.append(f.name)
        elif f.vep is not None:
            inner.append(f"{vep_expression(f, header)} AS {f.name}")
            if not f.hidden:
                outer.append(f.name)
        elif f.derived:
            outer.append(f"({f.derived}) AS {f.name}")
    return ",\n    ".join(inner), ",\n    ".join(outer)
