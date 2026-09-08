#!/usr/bin/env python3
"""Build data/phewas.duckdb from PheWAS sumstats + VEP annotation + phecode v1.2 definitions.

One-time build. Tables produced:
  phecode        1,817 phecode v1.2 definitions (code, description, category, color)
  annotation     one row per (variant, gene): MANE transcript preferred, else canonical
  assoc          slim sumstats: aOR + P + case/control + carrier counts for Meta/AoU/UKBB,
                 traits restricted to phecodes with a description; sorted by (gene, name, trait)
  variant_index  per (variant, gene): n_traits, top hit, carrier summary  (drives gene page)
  gene_summary   per gene: variant count, top hit                          (drives home page)
  rsid_map       rsID -> variant                                           (drives search)
"""

import argparse
import os
import time

import duckdb

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

# Defaults reproduce the original IEI build; every path can be overridden on the
# command line so the same script builds test fixtures and future datasets.
DEFAULT_DB = os.path.join(DATA, "phewas.duckdb")
DEFAULT_SUMSTATS = (
    "/Users/yluo/Work/PheWAS/IEI_haploinsufficiency/01_variant_level_meta/meta_IEI_AoU_UKBB.tsv.gz"
)
DEFAULT_ANNOTATION = "/Users/yluo/Work/PheWAS/IEI_haploinsufficiency/data/IEI_pilot_filtered_AoU_UKBB_V9.vep_50bpPTC.spliceAIfilled.tsv"
DEFAULT_PHECODE_CSV = os.path.join(DATA, "phecode_definitions1.2.csv")

SUMSTATS_TYPES = {
    "Name": "VARCHAR",
    "Chr": "VARCHAR",
    "Pos": "BIGINT",
    "Ref": "VARCHAR",
    "Alt": "VARCHAR",
    "Gene": "VARCHAR",
    "Consequence": "VARCHAR",
    "Trait": "VARCHAR",
    "Source": "VARCHAR",
    "Total_Cases": "BIGINT",
    "Total_Case_Carriers": "BIGINT",
    "Total_Controls": "BIGINT",
    "Total_Ctrl_Carriers": "BIGINT",
    "Cases_AoU": "BIGINT",
    "CaseCarr_AoU": "BIGINT",
    "Controls_AoU": "BIGINT",
    "CtrlCarr_AoU": "BIGINT",
    "Cases_UKBB": "BIGINT",
    "CaseCarr_UKBB": "BIGINT",
    "Controls_UKBB": "BIGINT",
    "CtrlCarr_UKBB": "BIGINT",
    "Beta_AoU": "DOUBLE",
    "SE_AoU": "DOUBLE",
    "Pval_AoU": "DOUBLE",
    "LOG10P_AoU": "DOUBLE",
    "OR_AoU": "DOUBLE",
    "AAF_AoU": "DOUBLE",
    "MAC_AoU": "DOUBLE",
    "Beta_UKBB": "DOUBLE",
    "SE_UKBB": "DOUBLE",
    "Pval_UKBB": "DOUBLE",
    "LOG10P_UKBB": "DOUBLE",
    "OR_UKBB": "DOUBLE",
    "AAF_UKBB": "DOUBLE",
    "MAC_UKBB": "DOUBLE",
    "Z_Meta": "DOUBLE",
    "Beta_Meta": "DOUBLE",
    "Meta_OR": "DOUBLE",
    "Meta_Pval": "DOUBLE",
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sumstats", default=DEFAULT_SUMSTATS, help="wide per-cohort sumstats TSV(.gz)")
    ap.add_argument("--annotation", default=DEFAULT_ANNOTATION, help="VEP annotation TSV")
    ap.add_argument("--phecodes", default=DEFAULT_PHECODE_CSV, help="phecode definitions CSV")
    ap.add_argument("--out", default=DEFAULT_DB, help="output DuckDB file (replaced if it exists)")
    ap.add_argument("--memory-limit", default="16GB", help="DuckDB memory_limit (e.g. 4GB)")
    ap.add_argument("--quiet", action="store_true", help="suppress progress output")
    return ap.parse_args(argv)


def build(sumstats, annotation, phecode_csv, db, memory_limit="16GB", quiet=False):
    """Build `db` from the three inputs. Returns a dict of sanity-check counts."""
    global log
    if quiet:
        log = lambda msg: None  # noqa: E731
    SUMSTATS, ANNOTATION, PHECODE_CSV, DB = sumstats, annotation, phecode_csv, db  # noqa: N806 (legacy names)
    TMP = os.path.join(os.path.dirname(os.path.abspath(DB)), "duckdb_tmp")  # noqa: N806
    os.makedirs(TMP, exist_ok=True)
    if os.path.exists(DB):
        os.remove(DB)
    con = duckdb.connect(DB)
    con.execute(f"SET temp_directory='{TMP}'")
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute("SET preserve_insertion_order=false")

    # ---------------- phecode definitions ----------------
    log("Loading phecode definitions...")
    con.execute(f"""
        CREATE TABLE phecode AS
        SELECT phecode, description, groupnum, "group" AS category, color
        FROM read_csv('{PHECODE_CSV}', header=true, types={{'phecode': 'VARCHAR'}})
    """)
    n_phe = con.sql("SELECT count(*) FROM phecode").fetchone()[0]
    log(f"  {n_phe} phecodes")

    # ---------------- annotation ----------------
    # One row per (variant, gene): prefer the MANE_SELECT transcript, then CANONICAL,
    # then any. Variant IDs are normalized to the sumstats form (no 'chr' prefix).
    log("Loading VEP annotation...")
    con.execute(f"""
        CREATE TEMP TABLE raw_ann AS
        SELECT * FROM read_csv('{ANNOTATION}', delim='\t', header=true,
                               all_varchar=true, quote='', sample_size=-1)
    """)
    # dbNSFP fields carry '&'-joined per-transcript values ("T&.&.&T"):
    # multi_pred keeps the distinct non-missing labels, multi_max the highest numeric value
    con.execute("""
        CREATE MACRO multi_pred(x) AS NULLIF(array_to_string(
            list_distinct(list_filter(string_split(x, '&'), y -> y NOT IN ('.', ''))), '/'), '')
    """)
    con.execute("""
        CREATE MACRO multi_max(x) AS list_max(
            list_transform(
                list_filter(string_split(x, '&'), y -> TRY_CAST(y AS DOUBLE) IS NOT NULL),
                y -> CAST(y AS DOUBLE)))
    """)
    # every '-' or '' becomes NULL, then typed columns are cast
    con.execute("""
        CREATE TABLE annotation AS
        WITH ranked AS (
            SELECT *,
                regexp_replace("#Uploaded_variation", '^chr', '') AS name,
                row_number() OVER (
                    PARTITION BY "#Uploaded_variation", SYMBOL
                    ORDER BY (NULLIF(MANE_SELECT, '-') IS NOT NULL) DESC,
                             (CANONICAL = 'YES') DESC,
                             Feature
                ) AS rn
            FROM raw_ann
        ),
        picked AS (SELECT * FROM ranked WHERE rn = 1),
        clean AS (
            SELECT
                name,
                SYMBOL                                        AS gene,
                string_split(name, ':')[1]                    AS chrom,
                CAST(string_split(name, ':')[2] AS BIGINT)    AS pos,
                string_split(name, ':')[3]                    AS ref,
                string_split(name, ':')[4]                    AS alt,
                Feature                                       AS transcript,
                NULLIF(MANE_SELECT, '-')                      AS mane_select,
                (CANONICAL = 'YES')                           AS canonical,
                NULLIF(Consequence, '-')                      AS consequence,
                NULLIF(IMPACT, '-')                           AS impact,
                NULLIF(EXON, '-')                             AS exon,
                NULLIF(INTRON, '-')                           AS intron,
                NULLIF(HGVSc, '-')                            AS hgvsc,
                NULLIF(HGVSp, '-')                            AS hgvsp,
                NULLIF(Existing_variation, '-')               AS existing_variation,
                NULLIF(CLIN_SIG, '-')                         AS clin_sig,
                TRY_CAST(NULLIF(gnomADe_AF, '-') AS DOUBLE)   AS gnomade_af,
                TRY_CAST(NULLIF(gnomADg_AF, '-') AS DOUBLE)   AS gnomadg_af,
                TRY_CAST(NULLIF(MAX_AF, '-') AS DOUBLE)       AS max_af,
                NULLIF(MAX_AF_POPS, '-')                      AS max_af_pops,
                TRY_CAST(NULLIF(gnomADe_AFR_AF, '-') AS DOUBLE) AS e_afr,
                TRY_CAST(NULLIF(gnomADe_AMR_AF, '-') AS DOUBLE) AS e_amr,
                TRY_CAST(NULLIF(gnomADe_EAS_AF, '-') AS DOUBLE) AS e_eas,
                TRY_CAST(NULLIF(gnomADe_NFE_AF, '-') AS DOUBLE) AS e_nfe,
                TRY_CAST(NULLIF(gnomADe_SAS_AF, '-') AS DOUBLE) AS e_sas,
                TRY_CAST(NULLIF(gnomADg_AFR_AF, '-') AS DOUBLE) AS g_afr,
                TRY_CAST(NULLIF(gnomADg_AMR_AF, '-') AS DOUBLE) AS g_amr,
                TRY_CAST(NULLIF(gnomADg_EAS_AF, '-') AS DOUBLE) AS g_eas,
                TRY_CAST(NULLIF(gnomADg_NFE_AF, '-') AS DOUBLE) AS g_nfe,
                TRY_CAST(NULLIF(gnomADg_SAS_AF, '-') AS DOUBLE) AS g_sas,
                COALESCE(TRY_CAST(NULLIF(CADD_PHRED, '-') AS DOUBLE),
                         TRY_CAST(NULLIF(CADD_phred, '-') AS DOUBLE)) AS cadd_phred,
                multi_max(NULLIF(REVEL_score, '-'))           AS revel_score,
                multi_pred(NULLIF(AlphaMissense_pred, '-'))   AS alphamissense_pred,
                multi_max(NULLIF(AlphaMissense_score, '-'))   AS alphamissense_score,
                multi_pred(NULLIF(MetaRNN_pred, '-'))         AS metarnn_pred,
                multi_max(NULLIF(MetaRNN_score, '-'))         AS metarnn_score,
                multi_pred(NULLIF(PrimateAI_pred, '-'))       AS primateai_pred,
                multi_pred(NULLIF(SIFT_pred, '-'))            AS sift_pred,
                NULLIF(PolyPhen, '-')                         AS polyphen,
                multi_max(NULLIF(phyloP100way_vertebrate, '-')) AS phylop100way,
                NULLIF(ClinVar_CLNSIG, '-')                   AS clinvar_clnsig,
                NULLIF(ClinVar_CLNSIGCONF, '-')               AS clinvar_clnsigconf,
                NULLIF(ClinVar_CLNREVSTAT, '-')               AS clinvar_clnrevstat,
                NULLIF(ClinVar_CLNDN, '-')                    AS clinvar_clndn,
                TRY_CAST(NULLIF(SpliceAI_pred_DS_AG, '-') AS DOUBLE) AS spliceai_ds_ag,
                TRY_CAST(NULLIF(SpliceAI_pred_DS_AL, '-') AS DOUBLE) AS spliceai_ds_al,
                TRY_CAST(NULLIF(SpliceAI_pred_DS_DG, '-') AS DOUBLE) AS spliceai_ds_dg,
                TRY_CAST(NULLIF(SpliceAI_pred_DS_DL, '-') AS DOUBLE) AS spliceai_ds_dl,
                TRY_CAST(NULLIF(SpliceAI_max_DS, '-') AS DOUBLE)     AS spliceai_max_ds,
                NULLIF(SpliceAI_source, '-')                  AS spliceai_source,
                NULLIF("50_BP_RULE_recomputed", '-')          AS rule_50bp_recomputed,
                NULLIF(LoF, '-')                              AS lof,
                NULLIF(LoF_filter, '-')                       AS lof_filter,
                NULLIF(LoF_flags, '-')                        AS lof_flags,
                NULLIF(LoF_info, '-')                         AS lof_info,
                TRY_CAST(NULLIF(LoGoFunc_GOF, '-') AS DOUBLE) AS logofunc_gof,
                TRY_CAST(NULLIF(LoGoFunc_LOF, '-') AS DOUBLE) AS logofunc_lof,
                TRY_CAST(NULLIF(LoGoFunc_neutral, '-') AS DOUBLE) AS logofunc_neutral,
                NULLIF(LoGoFunc_prediction, '-')              AS logofunc_prediction,
                TRY_CAST(NULLIF(PromoterAI_score, '-') AS DOUBLE) AS promoterai_score
            FROM picked
        )
        SELECT * EXCLUDE (e_afr, e_amr, e_eas, e_nfe, e_sas, g_afr, g_amr, g_eas, g_nfe, g_sas),
            -- popmax across the non-bottlenecked gnomAD pops (AFR/AMR/EAS/NFE/SAS, exomes+genomes)
            greatest(e_afr, e_amr, e_eas, e_nfe, e_sas, g_afr, g_amr, g_eas, g_nfe, g_sas) AS gnomad_popmax_af,
            CASE greatest(e_afr, e_amr, e_eas, e_nfe, e_sas, g_afr, g_amr, g_eas, g_nfe, g_sas)
                WHEN NULL THEN NULL
                WHEN e_afr THEN 'AFR (exomes)' WHEN e_amr THEN 'AMR (exomes)'
                WHEN e_eas THEN 'EAS (exomes)' WHEN e_nfe THEN 'NFE (exomes)'
                WHEN e_sas THEN 'SAS (exomes)'
                WHEN g_afr THEN 'AFR (genomes)' WHEN g_amr THEN 'AMR (genomes)'
                WHEN g_eas THEN 'EAS (genomes)' WHEN g_nfe THEN 'NFE (genomes)'
                WHEN g_sas THEN 'SAS (genomes)'
            END AS gnomad_popmax_pop
        FROM clean
    """)
    n_ann = con.sql("SELECT count(*) FROM annotation").fetchone()[0]
    log(f"  {n_ann} (variant, gene) annotation rows")

    # ---------------- sumstats ----------------
    log("Ingesting sumstats (this is the slow step)...")
    t0 = time.time()
    types_sql = "{" + ", ".join(f"'{k}': '{v}'" for k, v in SUMSTATS_TYPES.items()) + "}"
    con.execute(f"""
        CREATE TABLE assoc AS
        SELECT
            s.Name                 AS name,
            s.Gene                 AS gene,
            s.Trait                AS trait,
            s.Source               AS source,
            s.Meta_OR              AS or_meta,
            s.Meta_Pval            AS p_meta,
            CAST(s.Total_Cases AS INTEGER)          AS cases_meta,
            CAST(s.Total_Case_Carriers AS INTEGER)  AS casecarr_meta,
            CAST(s.Total_Controls AS INTEGER)       AS controls_meta,
            CAST(s.Total_Ctrl_Carriers AS INTEGER)  AS ctrlcarr_meta,
            s.OR_AoU               AS or_aou,
            s.Pval_AoU             AS p_aou,
            CAST(s.Cases_AoU AS INTEGER)            AS cases_aou,
            CAST(s.CaseCarr_AoU AS INTEGER)         AS casecarr_aou,
            CAST(s.Controls_AoU AS INTEGER)         AS controls_aou,
            CAST(s.CtrlCarr_AoU AS INTEGER)         AS ctrlcarr_aou,
            s.OR_UKBB              AS or_ukbb,
            s.Pval_UKBB            AS p_ukbb,
            CAST(s.Cases_UKBB AS INTEGER)           AS cases_ukbb,
            CAST(s.CaseCarr_UKBB AS INTEGER)        AS casecarr_ukbb,
            CAST(s.Controls_UKBB AS INTEGER)        AS controls_ukbb,
            CAST(s.CtrlCarr_UKBB AS INTEGER)        AS ctrlcarr_ukbb
        FROM read_csv('{SUMSTATS}', delim='\t', header=true, nullstr='NA',
                      types={types_sql}) s
        WHERE s.Trait IN (SELECT phecode FROM phecode)
        ORDER BY gene, name, trait
    """)
    n_assoc = con.sql("SELECT count(*) FROM assoc").fetchone()[0]
    log(f"  {n_assoc} association rows kept ({time.time() - t0:.0f}s)")

    # ---------------- derived tables ----------------
    log("Building variant_index / gene_summary / rsid_map...")
    con.execute("""
        CREATE TABLE variant_index AS
        SELECT
            a.name, a.gene,
            count(*)                    AS n_traits,
            min(a.p_meta)               AS min_p,
            arg_min(a.trait, a.p_meta)  AS top_trait,
            arg_min(a.or_meta, a.p_meta) AS top_or,
            max(a.casecarr_meta + a.ctrlcarr_meta) AS n_carriers,
            max(a.source)               AS source_any
        FROM assoc a
        GROUP BY a.name, a.gene
    """)
    con.execute("""
        CREATE TABLE gene_summary AS
        SELECT
            v.gene,
            min(ann.chrom)              AS chrom,
            min(ann.pos)                AS min_pos,
            max(ann.pos)                AS max_pos,
            count(*)                    AS n_variants,
            min(v.min_p)                AS min_p,
            arg_min(v.name, v.min_p)    AS top_variant,
            arg_min(v.top_trait, v.min_p) AS top_trait
        FROM variant_index v
        LEFT JOIN annotation ann ON ann.name = v.name AND ann.gene = v.gene
        GROUP BY v.gene
    """)
    con.execute("""
        CREATE TABLE rsid_map AS
        SELECT DISTINCT trim(x) AS rsid, name, gene
        FROM (
            SELECT unnest(string_split(replace(existing_variation, '&', ','), ',')) AS x,
                   name, gene
            FROM annotation
            WHERE existing_variation IS NOT NULL
        )
        WHERE trim(x) LIKE 'rs%'
    """)

    # ---------------- report ----------------
    log("Sanity checks...")
    counts = {}
    for label, q in [
        ("assoc rows", "SELECT count(*) FROM assoc"),
        ("variants in assoc", "SELECT count(*) FROM variant_index"),
        ("genes in assoc", "SELECT count(*) FROM gene_summary"),
        ("traits kept", "SELECT count(DISTINCT trait) FROM assoc"),
        (
            "variant-gene pairs missing annotation",
            "SELECT count(*) FROM variant_index v WHERE NOT EXISTS "
            "(SELECT 1 FROM annotation a WHERE a.name=v.name AND a.gene=v.gene)",
        ),
        ("rsIDs", "SELECT count(*) FROM rsid_map"),
    ]:
        counts[label] = con.sql(q).fetchone()[0]
        log(f"  {label}: {counts[label]}")

    con.close()
    log(f"Done. DB size: {os.path.getsize(DB) / 1e9:.2f} GB -> {DB}")
    return counts


def main(argv=None):
    a = parse_args(argv)
    build(a.sumstats, a.annotation, a.phecodes, a.out, memory_limit=a.memory_limit, quiet=a.quiet)


if __name__ == "__main__":
    main()
