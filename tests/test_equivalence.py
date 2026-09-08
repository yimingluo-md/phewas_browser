"""The phewas_core pipeline + legacy_api adapter must reproduce the legacy build_db.py results
value for value on the same inputs. This is the migration safety net."""

import math

import pytest

from tests.conftest import _make_client


@pytest.fixture(scope="module")
def pair(synthetic, library):
    legacy, _ = _make_client(synthetic["db"])
    core, _ = _make_client(synthetic["core_db"])
    with legacy, core:
        yield legacy, core


def _close(a, b, rel=1e-6):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(float(a), float(b), rel_tol=rel, abs_tol=1e-300)
    return a == b


def test_meta_identical(pair):
    legacy, core = pair
    a, b = legacy.get("/api/meta").json(), core.get("/api/meta").json()
    assert a["stats"] == b["stats"]
    assert [g["gene"] for g in a["genes"]] == [g["gene"] for g in b["genes"]]
    for ga, gb in zip(a["genes"], b["genes"], strict=True):
        for k in ("chrom", "min_pos", "max_pos", "n_variants", "top_variant", "top_trait", "top_trait_desc"):
            assert ga[k] == gb[k], (ga["gene"], k)
        assert _close(ga["min_p"], gb["min_p"])


def test_gene_page_identical(pair, synthetic):
    legacy, core = pair
    for gene in synthetic["genes"]:
        a, b = legacy.get(f"/api/gene/{gene}").json(), core.get(f"/api/gene/{gene}").json()
        assert [v["name"] for v in a["variants"]] == [v["name"] for v in b["variants"]]
        for va, vb in zip(a["variants"], b["variants"], strict=True):
            for k, x in va.items():
                assert k in vb, k
                assert _close(x, vb[k]), (gene, va["name"], k, x, vb[k])


def test_variant_page_identical(pair, synthetic):
    legacy, core = pair
    for v in synthetic["variants"][:12]:
        url = f"/api/variant/{v['name']}?gene={v['gene']}"
        a, b = legacy.get(url).json(), core.get(url).json()
        assert a["gene"] == b["gene"] and a["genes_for_variant"] == b["genes_for_variant"]
        for k, x in a["annotation"].items():
            assert _close(x, b["annotation"].get(k)), (v["name"], "annotation", k, x, b["annotation"].get(k))
        assert [r["trait"] for r in a["associations"]] == [r["trait"] for r in b["associations"]]
        for ra, rb in zip(a["associations"], b["associations"], strict=True):
            for k, x in ra.items():
                assert _close(x, rb.get(k)), (v["name"], ra["trait"], k, x, rb.get(k))


def test_search_identical(pair, synthetic):
    legacy, core = pair
    for term in ("GENE", "gen", synthetic["variants"][2]["name"][:6], "chr7:55", "rs1"):
        a, b = (
            legacy.get("/api/search", params={"term": term}).json(),
            core.get("/api/search", params={"term": term}).json(),
        )
        assert a == b, term
