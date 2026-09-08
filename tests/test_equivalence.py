"""The phewas_core importer must reproduce the legacy build_db.py results value for value on the
same inputs (scripts/compare_with_legacy.py is the same check users run on real data)."""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_new_pipeline_matches_legacy(synthetic, library, capsys):
    sys.path.insert(0, str(ROOT / "scripts"))
    import compare_with_legacy

    rc = compare_with_legacy.main([synthetic["db"], "--home", str(library.home), "--sample", "200"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "RESULT: identical" in out
    assert out.count("OK  ") >= 10 and "DIFF" not in out


def test_equivalence_detects_a_numeric_value_lost_to_null(synthetic, library, tmp_path, capsys):
    import duckdb

    sys.path.insert(0, str(ROOT / "scripts"))
    import compare_with_legacy

    home = tmp_path / "home"
    shutil.copytree(library.home, home)
    db = home / "datasets" / library.current().id / "dataset.duckdb"
    with duckdb.connect(str(db)) as con:
        assert con.execute("SELECT count(*) FROM annotation WHERE cadd_phred IS NOT NULL").fetchone()[0] > 0
        con.execute("UPDATE annotation SET cadd_phred = NULL")
    assert compare_with_legacy.main([synthetic["db"], "--home", str(home)]) == 1
    assert "DIFF annotation values" in capsys.readouterr().out
