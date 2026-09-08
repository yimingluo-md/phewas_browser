"""The import pipeline: sumstats (+ dictionary, + optional annotation) -> one dataset directory.

    sniff -> stage (sorted wide/long copy) -> variants & cohorts -> unpivot in chunks
    -> annotation -> derived summaries -> manifest -> finalize (atomic rename)

Memory is bounded by DuckDB's memory_limit (default: half of physical RAM) and by
processing associations in chunks of ~CHUNK_ROWS staged rows, so a 70 M-row file
imports on a laptop and the job reports progress after every chunk.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

import duckdb

from . import __version__
from ._db import count
from .annotation import import_vep
from .dictionaries import Dictionary, load_into, resolve
from .fields import stored_fields
from .manifest import STATISTICS, Cohort, Manifest, Source
from .profiles import CohortSpec, Profile, ProfileError, get_profile, match_profile
from .registry import DB_FILENAME, MANIFEST_FILENAME, DatasetRef, Library
from .schema import create_schema, derive_summaries

CHUNK_ROWS = 250_000
INT_STATS = {"cases", "case_carriers", "controls", "ctrl_carriers"}

ProgressFn = Callable[[str, int, int, str], None]


@dataclass
class ImportRequest:
    sumstats: Path
    name: str
    dictionary: str = "phecode-1.2"
    profile: str | None = None  # None = auto-detect
    annotation: Path | None = None
    build: str | None = None
    notes: str = "Research Use Only — do not disseminate."
    memory_limit: str | None = None
    threads: int | None = None
    make_current: bool = True
    hash_sources: bool = True


@dataclass
class ImportResult:
    ref: DatasetRef
    manifest: Manifest
    seconds: float
    log_path: Path
    warnings: list[str] = field(default_factory=list)


class ImportFailedError(RuntimeError):
    pass


# ---------------------------------------------------------------- helpers


def default_memory_limit() -> str:
    try:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        total = 8 * 2**30
    return f"{max(1, int(total / 2**30 / 2))}GB"


def sha256_of(path: Path, progress: ProgressFn | None = None) -> str:
    h = hashlib.sha256()
    size = path.stat().st_size
    done = 0
    with open(path, "rb") as f:
        while chunk := f.read(8 * 2**20):
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress("hash", done, size, path.name)
    return h.hexdigest()


def sniff_header(con: duckdb.DuckDBPyConnection, path: Path, delimiter: str) -> list[str]:
    rows = con.execute(
        "DESCRIBE SELECT * FROM read_csv(?, delim=?, header=true, all_varchar=true, sample_size=100)",
        [str(path), delimiter],
    ).fetchall()
    return [r[0] for r in rows]


def _q(col: str) -> str:
    return '"' + col.replace('"', '""') + '"'


def _stage_types(profile: Profile, cohorts: list[CohortSpec]) -> dict[str, str]:
    types = {c: "VARCHAR" for c in profile.keys.values()}
    for k, c in profile.variant_columns.items():
        types[c] = "BIGINT" if k == "pos" else "VARCHAR"
    if profile.kind == "wide":
        for spec in cohorts:
            for stat, col in spec.columns.items():
                types[col] = "BIGINT" if stat in INT_STATS else "DOUBLE"
    else:
        for stat, col in profile.stat_columns.items():
            types[col] = "BIGINT" if stat in INT_STATS else "DOUBLE"
    return types


# ---------------------------------------------------------------- the job


class Importer:
    def __init__(self, library: Library, request: ImportRequest, progress: ProgressFn | None = None):
        self.lib = library
        self.req = request
        self.progress = progress or (lambda *a: None)
        self.warnings: list[str] = []
        self.log_lines: list[str] = []
        self.t0 = time.time()

    # ---- logging ---------------------------------------------------------
    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')} +{time.time() - self.t0:6.1f}s] {msg}"
        self.log_lines.append(line)
        if self.log_file:
            self.log_file.write(line + "\n")
            self.log_file.flush()

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        self.log("WARNING: " + msg)

    def step(self, name: str, done: int = 0, total: int = 1, msg: str = "") -> None:
        self.progress(name, done, total, msg)

    # ---- run ---------------------------------------------------------------
    def run(self) -> ImportResult:
        req = self.req
        if not Path(req.sumstats).exists():
            raise FileNotFoundError(req.sumstats)
        if req.annotation is not None and not Path(req.annotation).exists():
            raise FileNotFoundError(req.annotation)
        dictionary = resolve(req.dictionary)

        dataset_id = self.lib.new_id()
        partial = self.lib.partial_dir(dataset_id)
        self.log_file = open(partial / "import.log", "w", encoding="utf-8")  # noqa: SIM115
        try:
            self.log(f"phewas_core {__version__} · duckdb {duckdb.__version__} · dataset {dataset_id}")
            self.log(f"sumstats: {req.sumstats}")
            con = duckdb.connect(str(partial / DB_FILENAME))
            tmp = partial / "tmp"
            tmp.mkdir()
            con.execute(f"SET temp_directory='{tmp}'")
            con.execute(f"SET memory_limit='{req.memory_limit or default_memory_limit()}'")
            if req.threads:
                con.execute(f"SET threads={req.threads}")
            con.execute("SET preserve_insertion_order=true")
            create_schema(con)

            # 1. sniff + profile
            self.step("sniff", 0, 1, "reading header")
            header = self._sniff(con)
            profile = self._resolve_profile(header)
            cohorts = profile.cohorts_for_header(header) if profile.kind == "wide" else []
            self.log(
                f"profile: {profile.name} ({profile.kind}); cohorts: {[c.id for c in cohorts] or 'from data'}"
            )

            # 2. dictionary
            self.step("dictionary", 0, 1, dictionary.label)
            n_traits_dict = load_into(con, dictionary)
            self.log(f"dictionary {dictionary.id}: {n_traits_dict} traits")

            # 3. stage
            self.step("stage", 0, 1, "reading and sorting the sumstats file")
            n_stage, n_dropped_traits = self._stage(con, profile, cohorts)
            self.log(f"staged {n_stage:,} rows; {n_dropped_traits} trait codes dropped (not in dictionary)")
            if n_stage == 0:
                raise ImportFailedError("no association rows left after applying the trait dictionary")

            # 4. variants + cohorts
            self._variants(con, profile)
            cohort_rows = self._cohorts(con, profile, cohorts)

            # 5. associations
            n_assoc = self._unpivot(con, profile, cohorts)
            con.execute("DROP TABLE stage")
            self.log(f"assoc: {n_assoc:,} rows")

            # 6. annotation
            n_ann = 0
            if req.annotation is not None:
                self.step("annotation", 0, 1, Path(req.annotation).name)
                n_ann = import_vep(con, Path(req.annotation), profile.strip_chr_prefix)
                self.log(f"annotation: {n_ann:,} (variant, gene) rows")
                self._fill_variant_positions(con)
            missing = count(
                con,
                """SELECT count(*) FROM variant v WHERE NOT EXISTS
                   (SELECT 1 FROM annotation a WHERE a.variant_id = v.variant_id AND a.gene = v.gene)""",
            )
            if req.annotation is not None and missing:
                self.warn(f"{missing} variant-gene pairs have no annotation row")

            # 7. derived summaries
            self.step("derive", 0, 1, "variant index, gene summary, rsIDs")
            primary = next(c for c in cohort_rows if c.primary).id
            derive_summaries(con, primary)

            # 8. manifest
            self.step("finalize", 0, 1, "hashing sources and writing manifest")
            manifest = self._manifest(con, dataset_id, profile, cohort_rows, dictionary, n_ann)
            con.execute("INSERT INTO meta VALUES ('manifest', ?)", [manifest.dumps()])
            con.execute("CHECKPOINT")
            con.close()
            manifest.save(partial / MANIFEST_FILENAME)
            for p in tmp.iterdir():
                p.unlink()
            tmp.rmdir()
            self.log(f"done in {time.time() - self.t0:.1f}s")
        except BaseException:
            if self.log_file is not None:
                self.log_file.close()
                self.log_file = None
            failed = self.lib.home / "failed-imports"
            failed.mkdir(parents=True, exist_ok=True)
            # keep only the log for diagnosis; the half-built database is discarded
            shutil.copy(partial / "import.log", failed / f"{dataset_id}.log")
            shutil.rmtree(partial, ignore_errors=True)
            raise
        finally:
            if self.log_file is not None:
                self.log_file.close()
            self.log_file = None

        ref = self.lib.finalize(dataset_id, make_current=req.make_current)
        return ImportResult(ref, manifest, time.time() - self.t0, ref.dir / "import.log", self.warnings)

    log_file: TextIO | None = None

    # ---- steps ---------------------------------------------------------------
    def _sniff(self, con: duckdb.DuckDBPyConnection) -> list[str]:
        delim = "\t"
        if self.req.profile:
            delim = get_profile(self.req.profile, self.lib.home).delimiter
        header = sniff_header(con, Path(self.req.sumstats), delim)
        if len(header) == 1 and delim == "\t" and "," in header[0]:
            header = sniff_header(con, Path(self.req.sumstats), ",")
        self.log(f"header: {len(header)} columns")
        return header

    def _resolve_profile(self, header: list[str]) -> Profile:
        if self.req.profile:
            profile = get_profile(self.req.profile, self.lib.home)
            missing = profile.missing_columns(header)
            if missing:
                raise ProfileError(f"profile {profile.name}: columns missing from file: {missing}")
            return profile
        matched = match_profile(header, self.lib.home)
        if matched is None:
            raise ProfileError("no import profile matches this file's header; pass --profile or create one")
        return matched

    def _stage(
        self, con: duckdb.DuckDBPyConnection, profile: Profile, cohorts: list[CohortSpec]
    ) -> tuple[int, int]:
        req = self.req
        types = _stage_types(profile, cohorts)
        keys = profile.keys
        vid = _q(keys["variant_id"])
        if profile.strip_chr_prefix:
            vid = f"regexp_replace({vid}, '^chr', '')"
        select = [f"{vid} AS variant_id", f"{_q(keys['gene'])} AS gene", f"{_q(keys['trait'])} AS trait"]
        if profile.kind == "long":
            select.append(f"{_q(keys['cohort'])} AS cohort")
        for k, c in profile.variant_columns.items():
            select.append(f"{_q(c)} AS v_{k}")
        stat_cols = (
            sorted({c for s in cohorts for c in s.columns.values()})
            if profile.kind == "wide"
            else sorted(profile.stat_columns.values())
        )
        select += [_q(c) for c in stat_cols]
        types_sql = "{" + ", ".join(f"'{c}': '{t}'" for c, t in types.items()) + "}"
        nulls_sql = "[" + ", ".join("'" + n.replace("'", "''") + "'" for n in profile.nulls) + "]"
        where = "WHERE trait IN (SELECT trait FROM trait)" if profile.trait_filter == "in_dictionary" else ""
        order = "gene, variant_id, trait" + (", cohort" if profile.kind == "long" else "")
        con.execute(
            f"""
            CREATE TABLE stage AS
            SELECT * FROM (
                SELECT {", ".join(select)}
                FROM read_csv(?, delim=?, header=true, nullstr={nulls_sql}, types={types_sql})
            ) {where}
            ORDER BY {order}
        """,
            [str(req.sumstats), profile.delimiter],
        )
        n = count(con, "SELECT count(*) FROM stage")
        if profile.trait_filter == "in_dictionary":
            # count what was dropped without re-reading: distinct traits in file vs kept
            n_kept = count(con, "SELECT count(DISTINCT trait) FROM stage")
            n_all = count(
                con,
                f"SELECT count(DISTINCT {_q(keys['trait'])}) FROM read_csv(?, delim=?, header=true, all_varchar=true)",
                [str(req.sumstats), profile.delimiter],
            )
            dropped = n_all - n_kept
            if dropped:
                self.warn(
                    f"{dropped} trait codes in the file have no entry in dictionary {req.dictionary} and were dropped"
                )
        else:
            dropped = 0
        return n, dropped

    def _variants(self, con: duckdb.DuckDBPyConnection, profile: Profile) -> None:
        vc = profile.variant_columns
        chrom = "min(v_chrom)" if "chrom" in vc else "min(string_split(variant_id, ':')[1])"
        pos = "min(v_pos)" if "pos" in vc else "min(TRY_CAST(string_split(variant_id, ':')[2] AS BIGINT))"
        ref = "min(v_ref)" if "ref" in vc else "min(string_split(variant_id, ':')[3])"
        alt = "min(v_alt)" if "alt" in vc else "min(string_split(variant_id, ':')[4])"
        if profile.strip_chr_prefix and "chrom" in vc:
            chrom = "min(regexp_replace(v_chrom, '^chr', ''))"
        con.execute(f"""INSERT INTO variant
                        SELECT variant_id, gene, {chrom}, {pos}, {ref}, {alt}
                        FROM stage GROUP BY variant_id, gene""")
        n = count(con, "SELECT count(*) FROM variant")
        self.log(f"variants: {n:,} (variant, gene) pairs")

    def _cohorts(
        self, con: duckdb.DuckDBPyConnection, profile: Profile, cohorts: list[CohortSpec]
    ) -> list[Cohort]:
        rows: list[Cohort] = []
        if profile.kind == "wide":
            for spec in cohorts:
                rows.append(Cohort(spec.id, spec.label, spec.is_meta, False))
        else:
            ids = [r[0] for r in con.execute("SELECT DISTINCT cohort FROM stage ORDER BY cohort").fetchall()]
            metas = [i for i in ids if i in profile.meta_cohort_ids]
            for i in metas + [i for i in ids if i not in metas]:
                rows.append(Cohort(i, profile.cohort_labels.get(i, i), i in metas, False))
        if not rows:
            raise ImportFailedError("no cohorts found")
        primary = next((c for c in rows if c.is_meta), rows[0])
        primary.primary = True
        con.execute("DELETE FROM cohort")
        for i, c in enumerate(rows):
            con.execute("INSERT INTO cohort VALUES (?, ?, ?, ?, ?)", [c.id, c.label, i, c.is_meta, c.primary])
        self.log(f"cohorts: {[c.id + ('*' if c.primary else '') for c in rows]}")
        return rows

    def _chunks(self, con: duckdb.DuckDBPyConnection) -> list[tuple[str, str, str, int]]:
        """(gene, first_variant, last_variant, rows) ranges of about CHUNK_ROWS staged rows each,
        in sort order so inserts preserve (gene, variant_id, trait, cohort) ordering."""
        plan = con.execute(
            "SELECT gene, variant_id, count(*) FROM stage GROUP BY ALL ORDER BY gene, variant_id"
        ).fetchall()
        chunks: list[tuple[str, str, str, int]] = []
        cur_gene: str | None = None
        lo = hi = ""
        acc = 0
        for gene, vid, n in plan:
            if cur_gene is not None and (gene != cur_gene or acc + n > CHUNK_ROWS):
                chunks.append((cur_gene, lo, hi, acc))
                lo, acc = "", 0
            if not lo:
                lo = vid
            cur_gene, hi, acc = gene, vid, acc + n
        if cur_gene is not None:
            chunks.append((cur_gene, lo, hi, acc))
        return chunks

    def _unpivot(self, con: duckdb.DuckDBPyConnection, profile: Profile, cohorts: list[CohortSpec]) -> int:
        chunks = self._chunks(con)
        total = sum(c[3] for c in chunks)
        done = 0
        if profile.kind == "wide":
            parts = []
            for spec in cohorts:
                cols = []
                for stat in STATISTICS:
                    col = spec.columns.get(stat)
                    cols.append(f"{_q(col)} AS {_q(stat)}" if col else f"NULL AS {_q(stat)}")
                present = " OR ".join(f"{_q(c)} IS NOT NULL" for c in spec.columns.values())
                parts.append(f"""SELECT variant_id, gene, trait, '{spec.id}' AS cohort, {", ".join(cols)}
                                 FROM stage WHERE gene = ? AND variant_id BETWEEN ? AND ? AND ({present})""")
            body = " UNION ALL ".join(parts)
            nparams = len(cohorts)
        else:
            cols = []
            for stat in STATISTICS:
                col = profile.stat_columns.get(stat)
                cols.append(f"{_q(col)} AS {_q(stat)}" if col else f"NULL AS {_q(stat)}")
            body = f"""SELECT variant_id, gene, trait, cohort, {", ".join(cols)}
                       FROM stage WHERE gene = ? AND variant_id BETWEEN ? AND ?"""
            nparams = 1
        stat_list = ", ".join(_q(s) for s in STATISTICS)
        sql = f"""INSERT INTO assoc (variant_id, gene, trait, cohort, {stat_list})
                  SELECT variant_id, gene, trait, cohort, {stat_list} FROM ({body})
                  ORDER BY gene, variant_id, trait, cohort"""
        self.step("assoc", 0, total, f"{len(chunks)} chunks")
        for gene, lo, hi, n in chunks:
            con.execute(sql, [gene, lo, hi] * nparams)
            done += n
            self.step("assoc", done, total, gene)
        return count(con, "SELECT count(*) FROM assoc")

    def _fill_variant_positions(self, con: duckdb.DuckDBPyConnection) -> None:
        """Variant coordinates come from the sumstats; annotation fills gaps if any."""
        con.execute("""UPDATE variant SET chrom = a.chrom, pos = a.pos, ref = a.ref, alt = a.alt
                       FROM annotation a
                       WHERE a.variant_id = variant.variant_id AND a.gene = variant.gene AND variant.pos IS NULL""")

    def _manifest(
        self,
        con: duckdb.DuckDBPyConnection,
        dataset_id: str,
        profile: Profile,
        cohort_rows: list[Cohort],
        dictionary: Dictionary,
        n_ann: int,
    ) -> Manifest:
        req = self.req
        stats = {
            "n_genes": count(con, "SELECT count(*) FROM gene_summary"),
            "n_variants": count(con, "SELECT count(*) FROM variant"),
            "n_traits": count(con, "SELECT count(DISTINCT trait) FROM assoc"),
            # associations = (variant, trait) tests on the primary cohort; rows = all cohorts
            "n_assoc": count(
                con, "SELECT count(*) FROM assoc WHERE cohort = (SELECT id FROM cohort WHERE is_primary)"
            ),
            "n_assoc_rows": count(con, "SELECT count(*) FROM assoc"),
            "n_annotation": n_ann,
        }
        populated = [s for s in STATISTICS if count(con, f"SELECT count({_q(s)}) FROM assoc") > 0]
        sources = [
            Source(
                "sumstats",
                str(Path(req.sumstats).resolve()),
                bytes=Path(req.sumstats).stat().st_size,
                profile=profile.name,
            )
        ]
        if req.annotation is not None:
            sources.append(
                Source(
                    "annotation",
                    str(Path(req.annotation).resolve()),
                    bytes=Path(req.annotation).stat().st_size,
                    profile="vep-tsv",
                )
            )
        sources.append(
            Source(
                "dictionary",
                dictionary.path if dictionary.kind == "generic" else f"builtin:{dictionary.id}",
                profile=dictionary.kind,
            )
        )
        if req.hash_sources:
            for s in sources:
                if Path(s.path).exists():
                    s.sha256 = sha256_of(Path(s.path), self.progress)
        return Manifest(
            id=dataset_id,
            name=req.name,
            created=dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            app_version=__version__,
            duckdb_version=duckdb.__version__,
            cohorts=cohort_rows,
            statistics=populated,
            dictionary={"id": dictionary.id, "label": dictionary.label},
            annotation_fields=[f.name for f in stored_fields() if not f.structural] if n_ann else [],
            sources=sources,
            stats=stats,
            build=req.build,
            notes=req.notes,
            warnings=list(self.warnings),
        )


def run_import(library: Library, request: ImportRequest, progress: ProgressFn | None = None) -> ImportResult:
    return Importer(library, request, progress).run()
