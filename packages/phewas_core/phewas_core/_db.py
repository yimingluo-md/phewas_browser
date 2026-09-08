"""Tiny DuckDB helpers shared by the package (typed wrappers around fetchone)."""

from __future__ import annotations

from typing import Any

import duckdb


def scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | dict[str, Any] | None = None) -> Any:
    row = con.execute(sql, params or []).fetchone()
    return None if row is None else row[0]


def count(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | dict[str, Any] | None = None) -> int:
    v = scalar(con, sql, params)
    return int(v) if v is not None else 0
