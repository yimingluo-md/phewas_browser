# PheWAS Browser

A desktop app for browsing variant-level PheWAS summary statistics — offline, on your own
machine. Import a summary-statistics file (plus optional VEP annotation), keep several
datasets side by side, and explore genes, variants and phenotypes with Manhattan plots,
filterable tables and CSV export.

Developed by Yiming Luo. The application contains **no data**; datasets you import are
typically **Research Use Only — do not disseminate**.

## Install

Download the build for your machine from the repository's *Releases* (or from the artifacts
of an *Actions → Release build* run):

| Platform | File |
|---|---|
| macOS, Apple Silicon | `PheWAS Browser_…_aarch64.dmg` |
| macOS, Intel | `PheWAS Browser_…_x64.dmg` |
| Windows 10/11 | `PheWAS Browser_…_x64-setup.exe` |

Open the DMG and drag the app to *Applications*. Until the builds are signed with a
Developer ID (Phase 4), macOS will say the developer cannot be verified the first time:
right-click the app → **Open** → **Open**. Windows: *More info → Run anyway*.

## Use

1. **Import…** (or `File → Import Dataset…`): choose the summary-statistics file; the layout
   is detected from its header (the REGENIE meta-analysis layout with per-cohort columns is
   built in, as is a long one-row-per-cohort layout). Optionally add the VEP annotation TSV,
   a name and the genome build, then *Start import*. Progress is live; the original files are
   never modified.
2. Browse: the home page lists genes; a gene page lists its variants with annotation columns
   and filters; a variant page shows annotation cards, a PheWAS Manhattan plot and the
   association table with one column group per cohort.
3. **Library**: switch between datasets, rename or remove them. **Dataset details** shows
   the manifest, source files with checksums, import warnings and the log.

Datasets live in `~/Library/Application Support/PheWAS Browser` (macOS) or
`%LOCALAPPDATA%\PheWAS Browser` (Windows) — `File → Show Data Folder`.

## Command line (the same engine)

```bash
uv sync                                   # once; needs uv (https://docs.astral.sh/uv/)
uv run phewas import sumstats.tsv.gz --annotation vep.tsv --name "My study" --build GRCh38
uv run phewas list | info <id> | remove <id> | profiles
uv run phewas serve                       # the same UI in your web browser
uv run python scripts/compare_with_legacy.py legacy.duckdb   # value-for-value check against a Phase-0 database
```

The command-line UI needs the frontend built once (`cd apps/web && npm ci && npm run build`).

## How it is built

```
apps/desktop/    Tauri 2 shell (Rust): native window, menus, dialogs; starts the sidecar
packages/phewas_server/   FastAPI API v1 (token on a random loopback port), import jobs; frozen with PyInstaller as the sidecar
packages/phewas_core/     schema, field registry, import profiles, importer, dataset library, query layer, `phewas` CLI
apps/web/        the UI (TypeScript, Vite), served by the server; rendered from each dataset's manifest
```

`docs/ARCHITECTURE_PLAN.md` explains the design and the roadmap; `docs/adr/` records the
decisions; `CONTRIBUTING.md` has the developer setup. Releases are built by
`.github/workflows/release.yml` for macOS (arm64 and Intel) and Windows.
