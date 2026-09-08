"""Phenotype dictionaries: trait code -> description / category / colour.

`phecode-1.2` ships built in (public data from the PheWAS R package `pheinfo`). Any
other dictionary is a CSV/TSV with at least `trait, description` and optionally
`category, category_ord, color`. The dictionary is loaded into the dataset's `trait`
table at import time so each dataset is self-contained.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import duckdb

from ._db import count


@dataclass(frozen=True)
class Dictionary:
    id: str
    label: str
    path: str
    kind: str  # "phecode" | "generic"


def builtin_dictionaries() -> list[Dictionary]:
    base = resources.files("phewas_core.builtin.dictionaries")
    return [
        Dictionary(
            "phecode-1.2", "Phecode v1.2 (1,817 codes)", str(base / "phecode_definitions1.2.csv"), "phecode"
        )
    ]


def resolve(id_or_path: str) -> Dictionary:
    for d in builtin_dictionaries():
        if d.id == id_or_path:
            return d
    p = Path(id_or_path)
    if p.exists():
        return Dictionary(p.stem, p.name, str(p), "generic")
    raise FileNotFoundError(
        f"unknown dictionary {id_or_path!r}; built-in: {[d.id for d in builtin_dictionaries()]}"
    )


def load_into(con: duckdb.DuckDBPyConnection, d: Dictionary) -> int:
    """Fill the `trait` table from dictionary `d`; returns the number of traits."""
    con.execute("DELETE FROM trait")
    if d.kind == "phecode":
        con.execute(
            """INSERT INTO trait
               SELECT phecode, description, "group", groupnum, color
               FROM read_csv(?, header=true, types={'phecode': 'VARCHAR'})""",
            [d.path],
        )
    else:
        cols = {
            r[0]
            for r in con.execute(
                "DESCRIBE SELECT * FROM read_csv(?, header=true, all_varchar=true)", [d.path]
            ).fetchall()
        }
        need = {"trait", "description"}
        if not need <= cols:
            raise ValueError(f"dictionary {d.path} needs columns {sorted(need)}; has {sorted(cols)}")
        cat = "category" if "category" in cols else "NULL"
        ord_ = "TRY_CAST(category_ord AS SMALLINT)" if "category_ord" in cols else "NULL"
        color = "color" if "color" in cols else "NULL"
        con.execute(
            f"""INSERT INTO trait
                SELECT trait, description, {cat}, {ord_}, {color}
                FROM read_csv(?, header=true, all_varchar=true)""",
            [d.path],
        )
    return count(con, "SELECT count(*) FROM trait")
