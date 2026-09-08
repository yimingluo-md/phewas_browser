#!/usr/bin/env python3
"""Generate a small, fully synthetic PheWAS dataset in the *input* layouts the
browser ingests today, so the pipeline and API can be tested without real data.

Outputs (in OUT_DIR):
  sumstats.tsv.gz    wide per-cohort layout of meta_IEI_AoU_UKBB.tsv.gz (same header)
  annotation.tsv     VEP-style TSV with the columns scripts/build_db.py reads
Uses the public phecode v1.2 definitions shipped in data/.

Deliberately covers the awkward cases the real files contain: single-cohort rows
(Source = one cohort, meta columns passing through), NA values, traits that are
not phecodes (dropped on import), a variant annotated for two genes, MANE vs
canonical transcript duplicates, '&'-joined dbNSFP fields, '-' for missing.

Everything is deterministic for a given seed. Nothing here derives from real data.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import math
import os
import random
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PHECODE_CSV = os.path.join(ROOT, "data", "phecode_definitions1.2.csv")

GENES = [  # (gene, chrom, start) — fictional coordinates
    ("GENEA", "1", 1_000_000),
    ("GENEB", "7", 55_000_000),
    ("GENEX", "X", 70_000_000),
]
COHORTS = ["AoU", "UKBB"]

SUMSTATS_HEADER = [
    "Name",
    "Chr",
    "Pos",
    "Ref",
    "Alt",
    "Gene",
    "Consequence",
    "Trait",
    "Source",
    "Total_Cases",
    "Total_Case_Carriers",
    "Total_Controls",
    "Total_Ctrl_Carriers",
    "Cases_AoU",
    "CaseCarr_AoU",
    "Controls_AoU",
    "CtrlCarr_AoU",
    "Cases_UKBB",
    "CaseCarr_UKBB",
    "Controls_UKBB",
    "CtrlCarr_UKBB",
    "Beta_AoU",
    "SE_AoU",
    "Pval_AoU",
    "LOG10P_AoU",
    "OR_AoU",
    "AAF_AoU",
    "MAC_AoU",
    "Beta_UKBB",
    "SE_UKBB",
    "Pval_UKBB",
    "LOG10P_UKBB",
    "OR_UKBB",
    "AAF_UKBB",
    "MAC_UKBB",
    "Z_Meta",
    "Beta_Meta",
    "Meta_OR",
    "Meta_Pval",
]

ANNOTATION_HEADER = [
    "#Uploaded_variation",
    "Location",
    "Allele",
    "Gene",
    "Feature",
    "Feature_type",
    "Consequence",
    "IMPACT",
    "SYMBOL",
    "MANE_SELECT",
    "CANONICAL",
    "EXON",
    "INTRON",
    "HGVSc",
    "HGVSp",
    "Existing_variation",
    "CLIN_SIG",
    "gnomADe_AF",
    "gnomADg_AF",
    "MAX_AF",
    "MAX_AF_POPS",
    "gnomADe_AFR_AF",
    "gnomADe_AMR_AF",
    "gnomADe_EAS_AF",
    "gnomADe_NFE_AF",
    "gnomADe_SAS_AF",
    "gnomADg_AFR_AF",
    "gnomADg_AMR_AF",
    "gnomADg_EAS_AF",
    "gnomADg_NFE_AF",
    "gnomADg_SAS_AF",
    "CADD_PHRED",
    "CADD_phred",
    "REVEL_score",
    "AlphaMissense_pred",
    "AlphaMissense_score",
    "MetaRNN_pred",
    "MetaRNN_score",
    "PrimateAI_pred",
    "SIFT_pred",
    "PolyPhen",
    "phyloP100way_vertebrate",
    "ClinVar_CLNSIG",
    "ClinVar_CLNSIGCONF",
    "ClinVar_CLNREVSTAT",
    "ClinVar_CLNDN",
    "SpliceAI_pred_DS_AG",
    "SpliceAI_pred_DS_AL",
    "SpliceAI_pred_DS_DG",
    "SpliceAI_pred_DS_DL",
    "SpliceAI_max_DS",
    "SpliceAI_source",
    "50_BP_RULE_recomputed",
    "LoF",
    "LoF_filter",
    "LoF_flags",
    "LoF_info",
    "LoGoFunc_GOF",
    "LoGoFunc_LOF",
    "LoGoFunc_neutral",
    "LoGoFunc_prediction",
    "PromoterAI_score",
]

CONSEQUENCES = [
    ("missense_variant", "MODERATE"),
    ("stop_gained", "HIGH"),
    ("synonymous_variant", "LOW"),
    ("frameshift_variant", "HIGH"),
    ("splice_region_variant&intron_variant", "LOW"),
    ("intron_variant", "MODIFIER"),
    ("splice_donor_variant", "HIGH"),
]
AA = [
    "Ala",
    "Arg",
    "Asn",
    "Asp",
    "Cys",
    "Gln",
    "Glu",
    "Gly",
    "His",
    "Ile",
    "Leu",
    "Lys",
    "Met",
    "Phe",
    "Pro",
    "Ser",
    "Thr",
    "Trp",
    "Tyr",
    "Val",
]


def _fmt(x, nd=6):
    if x is None:
        return "NA"
    if isinstance(x, float):
        return f"{x:.{nd}g}"
    return str(x)


def _read_phecodes(n, rng):
    with open(PHECODE_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    rng.shuffle(rows)
    return [r["phecode"] for r in rows[:n]]


def make_variants(rng, n_per_gene):
    """Return list of dicts: name, chrom, pos, ref, alt, gene, consequence, impact."""
    variants = []
    bases = "ACGT"
    for gene, chrom, start in GENES:
        positions = sorted(rng.sample(range(start, start + 60_000), n_per_gene))
        for pos in positions:
            ref = rng.choice(bases)
            r = rng.random()
            if r < 0.8:
                alt = rng.choice([b for b in bases if b != ref])
            elif r < 0.9:  # insertion
                alt = ref + "".join(rng.choice(bases) for _ in range(rng.randint(1, 4)))
            else:  # deletion
                ref = ref + "".join(rng.choice(bases) for _ in range(rng.randint(1, 4)))
                alt = ref[0]
            csq, imp = rng.choice(CONSEQUENCES)
            variants.append(
                {
                    "name": f"{chrom}:{pos}:{ref}:{alt}",
                    "chrom": chrom,
                    "pos": pos,
                    "ref": ref,
                    "alt": alt,
                    "gene": gene,
                    "consequence": csq,
                    "impact": imp,
                }
            )
    # one variant shared by two genes (overlapping loci), as happens in the real annotation
    shared = dict(variants[0])
    shared["gene"] = GENES[1][0]
    variants.append(shared)
    return variants


def _assoc_row(rng, v, trait, source, ncase, nctrl):
    """One wide association row. `source` in {'AoU', 'UKBB', 'AoU+UKBB'}."""
    row = dict.fromkeys(SUMSTATS_HEADER, "NA")
    row.update(
        Name=v["name"],
        Chr=v["chrom"],
        Pos=v["pos"],
        Ref=v["ref"],
        Alt=v["alt"],
        Gene=v["gene"],
        Consequence=v["consequence"],
        Trait=trait,
        Source=source,
    )
    per = {}
    for c in COHORTS:
        if c not in source:
            continue
        cases = int(ncase * (0.4 if c == "AoU" else 0.6))
        controls = int(nctrl * (0.4 if c == "AoU" else 0.6))
        casecarr = rng.randint(0, 12)
        ctrlcarr = rng.randint(0, 60)
        beta = rng.gauss(0.2 if casecarr > 6 else 0.0, 0.6)
        se = abs(rng.gauss(0.5, 0.15)) + 0.05
        z = beta / se
        p = max(math.erfc(abs(z) / math.sqrt(2)), 1e-300)
        per[c] = dict(
            cases=cases,
            casecarr=casecarr,
            controls=controls,
            ctrlcarr=ctrlcarr,
            beta=beta,
            se=se,
            p=p,
            aaf=(casecarr + ctrlcarr) / (2 * (cases + controls)),
            mac=casecarr + ctrlcarr,
        )
        row[f"Cases_{c}"] = cases
        row[f"CaseCarr_{c}"] = casecarr
        row[f"Controls_{c}"] = controls
        row[f"CtrlCarr_{c}"] = ctrlcarr
        row[f"Beta_{c}"] = _fmt(beta)
        row[f"SE_{c}"] = _fmt(se)
        row[f"Pval_{c}"] = _fmt(p)
        row[f"LOG10P_{c}"] = _fmt(-math.log10(p))
        row[f"OR_{c}"] = _fmt(math.exp(beta))
        row[f"AAF_{c}"] = _fmt(per[c]["aaf"])
        row[f"MAC_{c}"] = _fmt(float(per[c]["mac"]))
    # meta: inverse-variance weighted when both cohorts present, pass-through otherwise
    w = {c: 1 / per[c]["se"] ** 2 for c in per}
    beta_m = sum(per[c]["beta"] * w[c] for c in per) / sum(w.values())
    se_m = math.sqrt(1 / sum(w.values()))
    z_m = beta_m / se_m
    p_m = max(math.erfc(abs(z_m) / math.sqrt(2)), 1e-300)
    row["Total_Cases"] = sum(per[c]["cases"] for c in per)
    row["Total_Case_Carriers"] = sum(per[c]["casecarr"] for c in per)
    row["Total_Controls"] = sum(per[c]["controls"] for c in per)
    row["Total_Ctrl_Carriers"] = sum(per[c]["ctrlcarr"] for c in per)
    row["Z_Meta"] = _fmt(z_m)
    row["Beta_Meta"] = _fmt(beta_m)
    row["Meta_OR"] = _fmt(math.exp(beta_m))
    row["Meta_Pval"] = _fmt(p_m)
    return row


def write_sumstats(path, rng, variants, traits):
    n_case = {t: rng.randint(200, 20000) for t in traits}
    n_ctrl = {t: rng.randint(100000, 400000) for t in traits}
    with gzip.open(path, "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SUMSTATS_HEADER, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for v in variants:
            # most variants have both cohorts; some are single-cohort throughout
            src = rng.choices(["AoU+UKBB", "AoU", "UKBB"], weights=[8, 1, 1])[0]
            for t in traits:
                w.writerow(_assoc_row(rng, v, t, src, n_case[t], n_ctrl[t]))


def _stable_id(prefix, key):
    """Deterministic fake Ensembl-style id (hash() is salted per process)."""
    return f"{prefix}0000{zlib.crc32(key.encode()) % 100000:05d}"


def _hgvs(rng, v, tx, protein_pos):
    c_pos = rng.randint(1, 3000)
    hgvsc = f"{tx}.1:c.{c_pos}{v['ref'][0]}>{v['alt'][0]}"
    if v["consequence"].startswith("missense"):
        a, b = rng.sample(AA, 2)
        hgvsp = f"ENSP0000{rng.randint(10000, 99999)}.1:p.{a}{protein_pos}{b}"
    elif v["consequence"] in ("stop_gained",):
        hgvsp = f"ENSP0000{rng.randint(10000, 99999)}.1:p.{rng.choice(AA)}{protein_pos}Ter"
    elif v["consequence"].startswith("frameshift"):
        hgvsp = f"ENSP0000{rng.randint(10000, 99999)}.1:p.{rng.choice(AA)}{protein_pos}fs"
    elif v["consequence"].startswith("synonymous"):
        a = rng.choice(AA)
        hgvsp = f"ENSP0000{rng.randint(10000, 99999)}.1:p.{a}{protein_pos}%3D"
    else:
        hgvsp = "-"
    return hgvsc, hgvsp


def write_annotation(path, rng, variants):
    """Two transcript rows per (variant, gene): the MANE Select one and a non-canonical one,
    so the importer's transcript preference is exercised."""
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ANNOTATION_HEADER, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for i, v in enumerate(variants):
            gene_id = _stable_id("ENSG", v["gene"])
            tx_mane = _stable_id("ENST", v["gene"] + "mane")
            tx_alt = _stable_id("ENST", v["gene"] + "alt")
            protein_pos = rng.randint(1, 900)
            hgvsc, hgvsp = _hgvs(rng, v, tx_mane, protein_pos)
            has_rs = rng.random() < 0.6
            rsid = f"rs{rng.randint(1_000_000, 999_999_999)}" if has_rs else "-"
            existing = rsid if has_rs else "-"
            if has_rs and rng.random() < 0.3:
                existing = f"{rsid}&COSV{rng.randint(10000000, 99999999)}"
            e_afs = [rng.choice([None, None, rng.random() * 1e-3]) for _ in range(5)]
            g_afs = [rng.choice([None, rng.random() * 1e-3]) for _ in range(5)]
            all_afs = [x for x in e_afs + g_afs if x is not None]
            max_af = max(all_afs) if all_afs else None
            missense = v["consequence"].startswith("missense")
            revel = (
                "&".join(_fmt(rng.random(), 3) if rng.random() < 0.7 else "." for _ in range(3))
                if missense
                else "-"
            )
            am_pred = (
                "&".join(
                    rng.choice(["likely_benign", "likely_pathogenic", "ambiguous", "."]) for _ in range(3)
                )
                if missense
                else "-"
            )
            am_score = "&".join(_fmt(rng.random(), 3) for _ in range(3)) if missense else "-"
            high = v["impact"] == "HIGH"
            lof = rng.choice(["HC", "LC"]) if high else "-"
            base = {
                "#Uploaded_variation": ("chr" if rng.random() < 0.5 else "") + v["name"],
                "Location": f"{v['chrom']}:{v['pos']}",
                "Allele": v["alt"],
                "Gene": gene_id,
                "Feature_type": "Transcript",
                "Consequence": v["consequence"],
                "IMPACT": v["impact"],
                "SYMBOL": v["gene"],
                "EXON": f"{rng.randint(1, 20)}/20" if v["impact"] != "MODIFIER" else "-",
                "INTRON": f"{rng.randint(1, 19)}/19" if v["impact"] == "MODIFIER" else "-",
                "HGVSc": hgvsc,
                "HGVSp": hgvsp,
                "Existing_variation": existing,
                "CLIN_SIG": rng.choice(
                    ["-", "-", "benign", "uncertain_significance", "pathogenic&likely_pathogenic"]
                ),
                "gnomADe_AF": _fmt(rng.random() * 1e-3) if rng.random() < 0.6 else "-",
                "gnomADg_AF": _fmt(rng.random() * 1e-3) if rng.random() < 0.5 else "-",
                "MAX_AF": _fmt(max_af) if max_af is not None else "-",
                "MAX_AF_POPS": rng.choice(["gnomADe_NFE", "gnomADg_AFR", "-"]) if max_af is not None else "-",
                "CADD_PHRED": _fmt(rng.uniform(0, 40), 3) if rng.random() < 0.9 else "-",
                "CADD_phred": "-",
                "REVEL_score": revel,
                "AlphaMissense_pred": am_pred,
                "AlphaMissense_score": am_score,
                "MetaRNN_pred": "&".join(rng.choice(["T", "D", "."]) for _ in range(3)) if missense else "-",
                "MetaRNN_score": "&".join(_fmt(rng.random(), 3) for _ in range(3)) if missense else "-",
                "PrimateAI_pred": rng.choice(["T", "D", "-"]) if missense else "-",
                "SIFT_pred": rng.choice(["T", "D", "T&D", "-"]) if missense else "-",
                "PolyPhen": rng.choice(["benign(0.01)", "probably_damaging(0.99)", "-"]) if missense else "-",
                "phyloP100way_vertebrate": "&".join(_fmt(rng.uniform(-2, 9), 3) for _ in range(2)),
                "ClinVar_CLNSIG": rng.choice(
                    ["-", "-", "Benign", "Uncertain_significance", "Pathogenic/Likely_pathogenic"]
                ),
                "ClinVar_CLNSIGCONF": "-",
                "ClinVar_CLNREVSTAT": rng.choice(["-", "criteria_provided&_single_submitter"]),
                "ClinVar_CLNDN": rng.choice(
                    ["-", "not_provided", "Immunodeficiency_X|Inborn_genetic_diseases"]
                ),
                "SpliceAI_pred_DS_AG": _fmt(rng.random() * 0.2, 2),
                "SpliceAI_pred_DS_AL": _fmt(rng.random() * 0.2, 2),
                "SpliceAI_pred_DS_DG": _fmt(rng.random() * 0.2, 2),
                "SpliceAI_pred_DS_DL": _fmt(rng.random(), 2),
                "SpliceAI_source": "precomputed"
                if len(v["ref"]) == 1 and len(v["alt"]) == 1
                else "BroadAPI_masked_d50",
                "50_BP_RULE_recomputed": rng.choice(["PASS", "FAIL", "-"]) if high else "-",
                "LoF": lof,
                "LoF_filter": "-" if lof != "LC" else "END_TRUNC",
                "LoF_flags": "-",
                "LoF_info": "PERCENTILE:0.42,GERP_DIST:123" if lof != "-" else "-",
                "LoGoFunc_GOF": _fmt(rng.random(), 3),
                "LoGoFunc_LOF": _fmt(rng.random(), 3),
                "LoGoFunc_neutral": _fmt(rng.random(), 3),
                "LoGoFunc_prediction": rng.choice(["GOF", "LOF", "Neutral"]),
                "PromoterAI_score": _fmt(rng.random() * 0.5, 3) if rng.random() < 0.3 else "-",
            }
            for k, a in zip(
                ["gnomADe_AFR_AF", "gnomADe_AMR_AF", "gnomADe_EAS_AF", "gnomADe_NFE_AF", "gnomADe_SAS_AF"],
                e_afs,
                strict=True,
            ):
                base[k] = _fmt(a) if a is not None else "-"
            for k, a in zip(
                ["gnomADg_AFR_AF", "gnomADg_AMR_AF", "gnomADg_EAS_AF", "gnomADg_NFE_AF", "gnomADg_SAS_AF"],
                g_afs,
                strict=True,
            ):
                base[k] = _fmt(a) if a is not None else "-"
            base["SpliceAI_max_DS"] = _fmt(
                max(
                    float(base[k])
                    for k in (
                        "SpliceAI_pred_DS_AG",
                        "SpliceAI_pred_DS_AL",
                        "SpliceAI_pred_DS_DG",
                        "SpliceAI_pred_DS_DL",
                    )
                ),
                2,
            )
            mane = dict(base, Feature=tx_mane, MANE_SELECT=f"NM_{100000 + i}.2", CANONICAL="YES")
            alt = dict(
                base,
                Feature=tx_alt,
                MANE_SELECT="-",
                CANONICAL="-",
                HGVSc="-",
                HGVSp="-",
                Consequence="intron_variant",
                IMPACT="MODIFIER",
            )
            # write the non-MANE row first so ordering can't mask a wrong pick
            w.writerow(alt)
            w.writerow(mane)


def make_synthetic(out_dir, seed=0, n_variants_per_gene=20, n_traits=40, n_bad_traits=3):
    """Write sumstats.tsv.gz and annotation.tsv into out_dir; return their paths and the truth."""
    rng = random.Random(seed)
    os.makedirs(out_dir, exist_ok=True)
    variants = make_variants(rng, n_variants_per_gene)
    traits = _read_phecodes(n_traits, rng)
    # trait codes with no phecode v1.2 definition — must be dropped on import
    bad_traits = [f"9{k}.99" for k in range(n_bad_traits)]
    sumstats = os.path.join(out_dir, "sumstats.tsv.gz")
    annotation = os.path.join(out_dir, "annotation.tsv")
    write_sumstats(sumstats, rng, variants, traits + bad_traits)
    write_annotation(annotation, rng, variants)
    return {
        "sumstats": sumstats,
        "annotation": annotation,
        "phecodes": PHECODE_CSV,
        "variants": variants,
        "traits": traits,
        "bad_traits": bad_traits,
        "genes": [g for g, _, _ in GENES],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--variants-per-gene", type=int, default=20)
    ap.add_argument("--traits", type=int, default=40)
    a = ap.parse_args(argv)
    info = make_synthetic(a.out_dir, a.seed, a.variants_per_gene, a.traits)
    print(f"{len(info['variants'])} variant-gene pairs x {len(info['traits'])} traits -> {a.out_dir}")


if __name__ == "__main__":
    main()
