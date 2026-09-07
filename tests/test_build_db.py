"""The import pipeline on synthetic inputs: row accounting and the tricky transforms."""
import duckdb
import pytest


@pytest.fixture(scope="module")
def con(synthetic):
    c = duckdb.connect(synthetic["db"], read_only=True)
    yield c
    c.close()


def test_tables_exist(con):
    tables = {r[0] for r in con.sql("SHOW TABLES").fetchall()}
    assert {"phecode", "annotation", "assoc", "variant_index", "gene_summary", "rsid_map"} <= tables


def test_row_accounting(synthetic, con):
    n_pairs = len(synthetic["variants"])
    n_traits = len(synthetic["traits"])
    assert con.sql("SELECT count(*) FROM assoc").fetchone()[0] == n_pairs * n_traits
    assert con.sql("SELECT count(*) FROM variant_index").fetchone()[0] == n_pairs
    assert con.sql("SELECT count(*) FROM gene_summary").fetchone()[0] == len(synthetic["genes"])


def test_traits_without_phecode_definition_are_dropped(synthetic, con):
    kept = {r[0] for r in con.sql("SELECT DISTINCT trait FROM assoc").fetchall()}
    assert kept == set(synthetic["traits"])
    assert not kept & set(synthetic["bad_traits"])


def test_annotation_one_row_per_variant_gene_and_mane_preferred(synthetic, con):
    n = con.sql("SELECT count(*) FROM annotation").fetchone()[0]
    assert n == len(synthetic["variants"])
    assert con.sql("SELECT count(*) FROM annotation WHERE mane_select IS NULL").fetchone()[0] == 0
    assert con.sql("SELECT count(*) FROM annotation WHERE consequence = 'intron_variant' AND impact = 'MODIFIER' AND hgvsc IS NULL").fetchone()[0] == 0, \
        "the non-MANE transcript row was picked"


def test_chr_prefix_is_stripped_and_every_variant_annotated(con):
    assert con.sql("SELECT count(*) FROM annotation WHERE name LIKE 'chr%'").fetchone()[0] == 0
    missing = con.sql("""SELECT count(*) FROM variant_index v WHERE NOT EXISTS
                         (SELECT 1 FROM annotation a WHERE a.name = v.name AND a.gene = v.gene)""").fetchone()[0]
    assert missing == 0


def test_shared_variant_appears_under_both_genes(synthetic, con):
    shared = synthetic["variants"][0]["name"]
    genes = {r[0] for r in con.execute("SELECT gene FROM variant_index WHERE name = ?", [shared]).fetchall()}
    assert len(genes) == 2


def test_dbnsfp_collapsing(con):
    # multi_max: "0.12&.&0.9" -> 0.9 ; multi_pred: "T&.&D" -> "T/D" (distinct, no '.')
    r = con.sql("""SELECT count(*) FROM annotation
                   WHERE revel_score IS NOT NULL AND (revel_score < 0 OR revel_score > 1)""").fetchone()[0]
    assert r == 0
    preds = [r[0] for r in con.sql("SELECT alphamissense_pred FROM annotation WHERE alphamissense_pred IS NOT NULL").fetchall()]
    assert preds, "expected some AlphaMissense predictions"
    assert all("." not in p and "&" not in p for p in preds)


def test_popmax_is_max_of_pops(con):
    bad = con.sql("""SELECT count(*) FROM annotation
                     WHERE gnomad_popmax_af IS NOT NULL AND gnomad_popmax_pop IS NULL""").fetchone()[0]
    assert bad == 0


def test_single_cohort_rows_pass_through_to_meta(con):
    rows = con.sql("""SELECT or_meta, or_aou, or_ukbb, p_meta, p_aou FROM assoc
                      WHERE source = 'AoU' LIMIT 50""").fetchall()
    assert rows, "fixture should contain AoU-only rows"
    for or_meta, or_aou, or_ukbb, p_meta, p_aou in rows:
        assert or_ukbb is None
        assert or_meta == pytest.approx(or_aou, rel=1e-5)
        assert p_meta == pytest.approx(p_aou, rel=1e-5)


def test_variant_index_top_hit_is_min_p(con):
    bad = con.sql("""SELECT count(*) FROM variant_index v
                     JOIN assoc a ON a.name = v.name AND a.gene = v.gene AND a.trait = v.top_trait
                     WHERE a.p_meta <> v.min_p""").fetchone()[0]
    assert bad == 0


def test_rsid_map_only_rs_ids(con):
    assert con.sql("SELECT count(*) FROM rsid_map WHERE rsid NOT LIKE 'rs%'").fetchone()[0] == 0
    assert con.sql("SELECT count(*) FROM rsid_map").fetchone()[0] > 0
