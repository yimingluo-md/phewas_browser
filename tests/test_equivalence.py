"""The phewas_core importer must reproduce the legacy build_db.py results value for value on the
same inputs (scripts/compare_with_legacy.py is the same check users run on real data)."""

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
