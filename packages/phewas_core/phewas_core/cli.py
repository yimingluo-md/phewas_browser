"""`phewas` command line: import, list, info, current, remove, profiles, serve."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .importer import ImportRequest, run_import
from .profiles import all_profiles
from .registry import Library


def _lib(a: argparse.Namespace) -> Library:
    return Library(Path(a.home) if a.home else None)


def cmd_import(a: argparse.Namespace) -> int:
    lib = _lib(a)
    last: dict[str, str | None] = {"step": None}

    def progress(step: str, done: int, total: int, msg: str) -> None:
        if a.quiet:
            return
        if step != last["step"]:
            sys.stderr.write(f"\n{step:>11}: ")
            last["step"] = step
        if total > 1:
            sys.stderr.write(f"\r{step:>11}: {done:,}/{total:,} {msg}      ")
        else:
            sys.stderr.write(msg)
        sys.stderr.flush()

    req = ImportRequest(
        sumstats=Path(a.sumstats),
        name=a.name or Path(a.sumstats).name,
        dictionary=a.dictionary,
        profile=a.profile,
        annotation=Path(a.annotation) if a.annotation else None,
        build=a.build,
        memory_limit=a.memory_limit,
        threads=a.threads,
        make_current=not a.no_current,
        hash_sources=not a.no_hash,
    )
    res = run_import(lib, req, progress)
    if not a.quiet:
        sys.stderr.write("\n")
    m = res.manifest
    print(f'dataset {m.id} "{m.name}" in {res.seconds:.1f}s -> {res.ref.dir}')
    print(
        f"  {m.stats['n_genes']} genes, {m.stats['n_variants']:,} variants, {m.stats['n_traits']:,} traits, "
        f"{m.stats['n_assoc']:,} association rows; cohorts {[c.id for c in m.cohorts]}"
    )
    for w in res.warnings:
        print(f"  warning: {w}")
    return 0


def cmd_list(a: argparse.Namespace) -> int:
    lib = _lib(a)
    cur = lib.current()
    refs = lib.list()
    if not refs:
        print(f"no datasets in {lib.home}")
        return 0
    for r in refs:
        m = r.manifest()
        mark = "*" if cur and cur.id == r.id else " "
        print(
            f"{mark} {r.id}  {m.name}  ({m.stats.get('n_genes')} genes, {m.stats.get('n_variants'):,} variants, "
            f"cohorts {'/'.join(c.id for c in m.cohorts)}, {m.created})"
        )
    return 0


def cmd_info(a: argparse.Namespace) -> int:
    ref = _lib(a).get(a.dataset)
    print(json.dumps(ref.manifest().to_dict(), indent=2))
    return 0


def cmd_current(a: argparse.Namespace) -> int:
    lib = _lib(a)
    if a.dataset:
        lib.set_current(a.dataset)
    cur = lib.current()
    print(cur.id if cur else "")
    return 0


def cmd_remove(a: argparse.Namespace) -> int:
    lib = _lib(a)
    ref = lib.get(a.dataset)
    lib.remove(ref.id)
    print(f"removed {ref.id}")
    return 0


def cmd_profiles(a: argparse.Namespace) -> int:
    for p in all_profiles(_lib(a).home):
        print(f"{p.name:22} {p.kind:5} {p.label}   [{p.source_path}]")
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    import os

    lib = _lib(a)
    ref = lib.get(a.dataset) if a.dataset else lib.current()
    if ref is None:
        print("no dataset to serve; import one first", file=sys.stderr)
        return 1
    os.environ["IEI_PHEWAS_DB"] = str(ref.db_path)
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed in this environment", file=sys.stderr)
        return 1
    print(f"serving {ref.id} on http://127.0.0.1:{a.port}")
    uvicorn.run("app:app", host="127.0.0.1", port=a.port, log_level="warning")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="phewas", description="PheWAS Browser dataset library")
    ap.add_argument(
        "--home", help="library directory (default: $PHEWAS_HOME or the platform app-data folder)"
    )
    ap.add_argument("--version", action="version", version=f"phewas-core {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import", help="build a dataset from a sumstats file")
    p.add_argument("sumstats", help="sumstats TSV/CSV, optionally gzip-compressed")
    p.add_argument("--name", help="display name (default: file name)")
    p.add_argument("--annotation", help="VEP annotation TSV")
    p.add_argument("--dictionary", default="phecode-1.2", help="phenotype dictionary id or CSV path")
    p.add_argument("--profile", help="import profile name or JSON path (default: auto-detect)")
    p.add_argument("--build", help="genome build label, e.g. GRCh38")
    p.add_argument("--memory-limit", help="DuckDB memory limit, e.g. 8GB (default: half of RAM)")
    p.add_argument("--threads", type=int)
    p.add_argument("--no-current", action="store_true", help="do not make the new dataset current")
    p.add_argument("--no-hash", action="store_true", help="skip sha256 of source files")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(fn=cmd_import)

    sub.add_parser("list", help="list datasets").set_defaults(fn=cmd_list)
    p = sub.add_parser("info", help="print a dataset manifest")
    p.add_argument("dataset")
    p.set_defaults(fn=cmd_info)
    p = sub.add_parser("current", help="show or set the current dataset")
    p.add_argument("dataset", nargs="?")
    p.set_defaults(fn=cmd_current)
    p = sub.add_parser("remove", help="delete a dataset")
    p.add_argument("dataset")
    p.set_defaults(fn=cmd_remove)
    sub.add_parser("profiles", help="list import profiles").set_defaults(fn=cmd_profiles)
    p = sub.add_parser("serve", help="run the browser on a dataset (development)")
    p.add_argument("dataset", nargs="?")
    p.add_argument("--port", type=int, default=8555)
    p.set_defaults(fn=cmd_serve)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        rc: int = a.fn(a)
        return rc
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
