"""phewas_core unit/integration tests on the synthetic fixture."""

import csv
import gzip
import json
from pathlib import Path

import duckdb
import pytest
from phewas_core import SCHEMA_VERSION
from phewas_core.importer import Importer, ImportRequest, run_import
from phewas_core.manifest import STATISTICS, Manifest
from phewas_core.profiles import ProfileError, builtin_profiles, get_profile, match_profile
from phewas_core.query import Dataset, DatasetNotFoundError
from phewas_core.registry import Library
from phewas_core.schema import is_v1_dataset


# ---------------------------------------------------------------- profiles
def test_builtin_profiles_load_and_validate():
    names = {p.name for p in builtin_profiles()}
    assert {"regenie-meta-wide", "long"} <= names
    p = get_profile("regenie-meta-wide")
    assert p.kind == "wide" and p.meta_cohort_id == "META"


def test_profile_matching_on_synthetic_header(synthetic):
    with gzip.open(synthetic["sumstats"], "rt") as f:
        header = f.readline().rstrip("\n").split("\t")
    p = match_profile(header)
    assert p is not None and p.name == "regenie-meta-wide"
    specs = p.cohorts_for_header(header)
    assert [(s.id, s.is_meta) for s in specs] == [("META", True), ("AoU", False), ("UKBB", False)]
    assert "Beta_Meta" in p.meta_map  # must not be mistaken for a cohort called "Meta"


def test_profile_matching_unknown_header():
    assert match_profile(["foo", "bar"]) is None
    with pytest.raises(ProfileError):
        get_profile("does-not-exist")


# ---------------------------------------------------------------- import result
def test_import_layout_and_manifest(library, synthetic):
    res = synthetic["import_result"]
    ref = library.current()
    assert ref.id == res.ref.id
    assert (
        (ref.dir / "manifest.json").exists()
        and (ref.dir / "dataset.duckdb").exists()
        and (ref.dir / "import.log").exists()
    )
    assert not (ref.dir / "tmp").exists()
    m = Manifest.load(ref.manifest_path)
    assert m.schema_version == SCHEMA_VERSION
    assert [c.id for c in m.cohorts] == ["META", "AoU", "UKBB"] and m.primary_cohort.id == "META"
    assert m.stats["n_variants"] == len(synthetic["variants"])
    assert m.stats["n_traits"] == len(synthetic["traits"])
    assert m.stats["n_assoc"] == len(synthetic["variants"]) * len(synthetic["traits"])  # primary-cohort rows
    assert {s.role for s in m.sources} == {"sumstats", "annotation", "dictionary"}
    assert any("dropped" in w for w in m.warnings)
    # manifest is also embedded in the database
    con = duckdb.connect(str(ref.db_path), read_only=True)
    assert is_v1_dataset(con)
    embedded = json.loads(con.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
    assert embedded["id"] == m.id
    con.close()


def test_long_table_contents(synthetic):
    con = duckdb.connect(synthetic["core_db"], read_only=True)
    per_cohort = dict(con.execute("SELECT cohort, count(*) FROM assoc GROUP BY 1").fetchall())
    n_pairs, n_traits = len(synthetic["variants"]), len(synthetic["traits"])
    assert per_cohort["META"] == n_pairs * n_traits
    assert (
        per_cohort["AoU"] < per_cohort["META"] and per_cohort["UKBB"] < per_cohort["META"]
    )  # single-cohort rows exist
    # rows of a cohort that is absent for a variant are not stored
    assert (
        con.execute(
            'SELECT count(*) FROM assoc WHERE p IS NULL AND "or" IS NULL AND cases IS NULL'
        ).fetchone()[0]
        == 0
    )
    # META passes through the single cohort's estimate (legacy semantics preserved)
    r = con.execute("""SELECT count(*) FROM assoc m JOIN assoc a
                       ON a.variant_id=m.variant_id AND a.gene=m.gene AND a.trait=m.trait AND a.cohort='AoU'
                       WHERE m.cohort='META' AND NOT EXISTS (SELECT 1 FROM assoc u WHERE u.variant_id=m.variant_id AND u.gene=m.gene AND u.trait=m.trait AND u.cohort='UKBB')
                       AND abs(m.p - a.p) > 1e-9""").fetchone()[0]
    assert r == 0
    # sorted for zonemap pruning
    assert (
        con.execute("""SELECT count(*) FROM (SELECT gene, variant_id, trait, cohort,
                          lag((gene, variant_id, trait, cohort)) OVER () AS prev FROM assoc) WHERE prev > (gene, variant_id, trait, cohort)""").fetchone()[
            0
        ]
        == 0
    )
    con.close()


def test_variant_index_cohort_lists(synthetic):
    ds = Dataset(synthetic["core_db"])
    g = ds.gene_page(synthetic["genes"][0])
    kinds = {tuple(v["cohorts"]) for v in g["variants"]}
    assert ("AoU", "META", "UKBB") in kinds
    ds.close()


def test_query_layer_shapes(synthetic):
    ds = Dataset(synthetic["core_db"])
    m = ds.meta()
    assert m["primary_cohort"] == "META" and [c["id"] for c in m["cohorts"]] == ["META", "AoU", "UKBB"]
    assert {f["name"] for f in m["fields"]} >= {"cadd_phred", "consequence", "gnomad_popmax_af"}
    v = synthetic["variants"][4]
    page = ds.variant_page(v["name"], v["gene"])
    a = page["associations"][0]
    assert set(a["cohorts"]) <= {"META", "AoU", "UKBB"} and "META" in a["cohorts"]
    assert set(a["cohorts"]["META"]) == set(STATISTICS)
    with pytest.raises(DatasetNotFoundError):
        ds.gene_page("NOPE")
    with pytest.raises(DatasetNotFoundError):
        ds.variant_page("1:1:A:T")
    ds.close()


# ---------------------------------------------------------------- chunking
def test_chunk_plan_respects_gene_boundaries_and_size(synthetic, monkeypatch):
    import phewas_core.importer as imp

    con = duckdb.connect()
    con.execute(
        "CREATE TABLE stage AS SELECT gene, variant_id, trait FROM (VALUES "
        + ", ".join(f"('G{g}', 'v{v:03d}', 't{t}')" for g in range(2) for v in range(10) for t in range(50))
        + ") s(gene, variant_id, trait)"
    )
    monkeypatch.setattr(imp, "CHUNK_ROWS", 120)  # 2 variants (100 rows) per chunk, 3rd would exceed
    lib = Library(Path("/nonexistent-not-used"))
    chunks = Importer(lib, ImportRequest(Path("x"), "x"))._chunks(con)
    assert all(rows <= 120 for _, _, _, rows in chunks)
    assert sum(r for *_, r in chunks) == 1000
    assert [c[0] for c in chunks] == ["G0"] * 5 + ["G1"] * 5
    lo_hi = [(c[1], c[2]) for c in chunks]
    assert lo_hi[0] == ("v000", "v001") and lo_hi[4] == ("v008", "v009")


# ---------------------------------------------------------------- long profile + generic dictionary
def test_import_long_layout_with_generic_dictionary(tmp_path):
    rows = []
    for vid, gene in [("1:100:A:T", "GA"), ("1:200:G:C", "GA"), ("2:300:T:TA", "GB")]:
        for trait in ("T1", "T2", "T3"):
            for cohort, p in (("META", 0.01), ("C1", 0.02), ("C2", 0.03)):
                if vid == "2:300:T:TA" and cohort == "C2":
                    continue
                rows.append(
                    {
                        "variant_id": "chr" + vid,
                        "gene": gene,
                        "trait": trait,
                        "cohort": cohort,
                        "or": 1.5,
                        "p": p,
                        "beta": 0.4,
                        "se": 0.1,
                        "cases": 100,
                        "case_carriers": 3,
                        "controls": 1000,
                        "ctrl_carriers": 10,
                        "aaf": "NA",
                        "mac": 13,
                    }
                )
    sums = tmp_path / "long.tsv"
    with open(sums, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    dic = tmp_path / "dict.csv"
    dic.write_text(
        "trait,description,category,category_ord,color\nT1,Trait one,cat A,1,red\nT2,Trait two,cat A,1,red\nT3,Trait three,cat B,2,blue\n"
    )
    lib = Library(tmp_path / "home")
    res = run_import(
        lib, ImportRequest(sums, "long test", dictionary=str(dic), memory_limit="500MB", hash_sources=False)
    )
    m = res.manifest
    assert [c.id for c in m.cohorts] == ["META", "C1", "C2"] and m.primary_cohort.id == "META"
    assert m.stats == {
        "n_genes": 2,
        "n_variants": 3,
        "n_traits": 3,
        "n_assoc": 9,
        "n_assoc_rows": 24,
        "n_annotation": 0,
    }
    assert "aaf" not in m.statistics and "mac" in m.statistics
    ds = Dataset(res.ref.db_path)
    page = ds.variant_page("2:300:T:TA")
    assert page["gene"] == "GB" and set(page["associations"][0]["cohorts"]) == {"META", "C1"}
    assert (
        page["variant"]["chrom"] == "2" and page["variant"]["pos"] == 300 and page["variant"]["alt"] == "TA"
    )
    assert page["associations"][0]["description"] == "Trait one"
    assert (
        ds.gene_page("GA")["variants"][0]["pos"] == 100
    )  # coordinates parsed from the id, no annotation needed
    ds.close()
    assert lib.list()[0].id == res.ref.id


# ---------------------------------------------------------------- registry
def test_registry_lifecycle(tmp_path, synthetic):
    lib = Library(tmp_path / "home")
    assert lib.list() == [] and lib.current() is None
    r1 = run_import(
        lib, ImportRequest(Path(synthetic["sumstats"]), "first", memory_limit="500MB", hash_sources=False)
    ).ref
    r2 = run_import(
        lib,
        ImportRequest(
            Path(synthetic["sumstats"]),
            "second",
            memory_limit="500MB",
            hash_sources=False,
            make_current=False,
        ),
    ).ref
    assert [r.id for r in lib.list()] == [r1.id, r2.id]
    assert lib.current().id == r1.id
    lib.set_current(r2.id[:6])
    assert lib.current().id == r2.id
    assert lib.get(str(r1.dir)).id == r1.id
    lib.remove(r2.id)
    assert [r.id for r in lib.list()] == [r1.id] and lib.current().id == r1.id
    with pytest.raises(KeyError):
        lib.get("zzz")
    assert not list(lib.datasets_dir.glob("*.partial"))


def test_import_failure_leaves_no_partial_dataset(tmp_path):
    lib = Library(tmp_path / "home")
    bad = tmp_path / "bad.tsv"
    bad.write_text("a\tb\n1\t2\n")
    with pytest.raises(ProfileError):
        run_import(lib, ImportRequest(bad, "bad", memory_limit="500MB"))
    assert lib.list() == []
    assert not lib.registry_path.exists() or json.loads(lib.registry_path.read_text())["datasets"] == []


# ---------------------------------------------------------------- CLI
def test_cli_import_list_info(tmp_path, synthetic, capsys):
    from phewas_core.cli import main

    home = str(tmp_path / "home")
    rc = main(
        [
            "--home",
            home,
            "import",
            synthetic["sumstats"],
            "--annotation",
            synthetic["annotation"],
            "--name",
            "cli test",
            "--memory-limit",
            "500MB",
            "--no-hash",
            "--quiet",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "dataset " in out and '"cli test"' in out
    assert main(["--home", home, "list"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("*") and "cli test" in out
    ds_id = out.split()[1]
    assert main(["--home", home, "info", ds_id[:5]]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["name"] == "cli test" and info["stats"]["n_annotation"] == len(synthetic["variants"])
    assert main(["--home", home, "remove", ds_id]) == 0
    assert main(["--home", home, "list"]) == 0
    assert "no datasets" in capsys.readouterr().out
    assert main(["--home", home, "info", "nothing"]) == 2
