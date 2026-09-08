"""HTTP contract of the current FastAPI backend. These pin behaviour before the refactor."""

import math


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"application": "IEI PheWAS Browser", "status": "ok"}


def test_meta(client, synthetic):
    d = client.get("/api/meta").json()
    assert d["stats"]["n_genes"] == len(synthetic["genes"])
    assert d["stats"]["n_variants"] == len(synthetic["variants"])
    assert d["stats"]["n_traits"] == len(synthetic["traits"])
    assert d["stats"]["n_assoc"] == len(synthetic["variants"]) * len(synthetic["traits"])
    genes = [g["gene"] for g in d["genes"]]
    assert genes == sorted(synthetic["genes"])
    g0 = d["genes"][0]
    assert {
        "chrom",
        "min_pos",
        "max_pos",
        "n_variants",
        "min_p",
        "top_variant",
        "top_trait",
        "top_trait_desc",
    } <= g0.keys()


def test_search_gene_prefix(client):
    d = client.get("/api/search", params={"term": "gene"}).json()
    kinds = {r["type"] for r in d["results"]}
    assert "gene" in kinds
    assert any(r["id"] == "GENEA" for r in d["results"])


def test_search_variant_prefix_with_and_without_chr(client, synthetic):
    name = synthetic["variants"][3]["name"]
    for term in (name[:8], "chr" + name[:8]):
        d = client.get("/api/search", params={"term": term}).json()
        assert any(r["type"] == "variant" for r in d["results"]), term


def test_search_rsid(client, synthetic):
    import duckdb

    con = duckdb.connect(synthetic["db"], read_only=True)
    rsid = con.sql("SELECT rsid FROM rsid_map LIMIT 1").fetchone()[0]
    con.close()
    d = client.get("/api/search", params={"term": rsid[:6]}).json()
    assert any(r["type"] == "variant" and rsid in r["label"] for r in d["results"])


def test_search_requires_term(client):
    assert client.get("/api/search").status_code == 422
    assert client.get("/api/search", params={"term": ""}).status_code == 422


def test_gene_page(client, synthetic):
    d = client.get("/api/gene/GENEA").json()
    assert d["summary"]["gene"] == "GENEA"
    n = sum(1 for v in synthetic["variants"] if v["gene"] == "GENEA")
    assert len(d["variants"]) == n
    v = d["variants"][0]
    for k in (
        "name",
        "n_traits",
        "min_p",
        "top_trait",
        "top_or",
        "n_carriers",
        "pos",
        "consequence",
        "impact",
        "hgvsc",
        "hgvsp",
        "cadd_phred",
        "lof",
        "top_trait_desc",
    ):
        assert k in v
    positions = [v["pos"] for v in d["variants"]]
    assert positions == sorted(positions)


def test_gene_not_found(client):
    r = client.get("/api/gene/NOPE")
    assert r.status_code == 404


def test_variant_page(client, synthetic):
    v = synthetic["variants"][5]
    d = client.get(f"/api/variant/{v['name']}", params={"gene": v["gene"]}).json()
    assert d["name"] == v["name"] and d["gene"] == v["gene"]
    assert d["annotation"] is not None and d["annotation"]["gene"] == v["gene"]
    assert len(d["associations"]) == len(synthetic["traits"])
    a = d["associations"][0]
    for k in (
        "trait",
        "description",
        "category",
        "groupnum",
        "color",
        "source",
        "or_meta",
        "p_meta",
        "cases_meta",
        "casecarr_meta",
        "or_aou",
        "p_aou",
        "or_ukbb",
        "p_ukbb",
    ):
        assert k in a
    # JSON-safe: no NaN/Inf leaked
    for a in d["associations"]:
        for val in a.values():
            if isinstance(val, float):
                assert math.isfinite(val)


def test_variant_page_infers_gene_and_lists_all_genes(client, synthetic):
    shared = synthetic["variants"][0]["name"]
    d = client.get(f"/api/variant/{shared}").json()
    assert len(d["genes_for_variant"]) == 2
    assert d["gene"] in d["genes_for_variant"]


def test_variant_page_accepts_chr_prefix(client, synthetic):
    v = synthetic["variants"][7]
    d = client.get(f"/api/variant/chr{v['name']}", params={"gene": v["gene"]}).json()
    assert d["name"] == v["name"]


def test_variant_not_found(client):
    assert client.get("/api/variant/1:1:A:T").status_code == 404


def test_index_and_static(client):
    r = client.get("/")
    assert r.status_code == 200 and "IEI PheWAS Browser" in r.text
    assert client.get("/static/app.js").status_code == 200
