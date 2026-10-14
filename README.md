# PheWAS Browser

A desktop app for browsing variant-level PheWAS summary statistics — offline, on your own
machine. Import a summary-statistics file (plus optional VEP annotation), keep several
datasets side by side, and explore genes, variants and phenotypes with Manhattan plots,
filterable tables and CSV export.

Developed by Yiming Luo. The application contains **no data**; datasets you import are
typically **Research Use Only — do not disseminate**.

## Install

Download the app from [GitHub Releases](https://github.com/yimingluo-md/phewas_browser/releases/latest).
No GitHub account is needed to download a public release. Study data is distributed separately
as source files or a `.phewasds` dataset bundle (see [Sharing datasets](#sharing-datasets)).

| Platform | File |
|---|---|
| macOS, Apple Silicon (M1, M2, M3, M4 and later) | `PheWAS-Browser-0.5.0-macos-arm64.dmg` |
| macOS, Intel | `PheWAS-Browser-0.5.0-macos-intel.dmg` |

The public v0.5.0 release contains the signed and notarized macOS builds. Windows builds are
available to maintainers through GitHub Actions; Windows code signing is not configured.

Download the DMG in Safari or another web browser, open it, and drag the app to *Applications*.
If that folder requires an administrator password, create an `Applications` folder inside
your home folder and copy the app there instead. Launch the copied app. Institutional device
policies can still restrict application installation or execution.

Share the release link rather than attaching the app to email. Some attachment-saving
applications can add macOS sandbox-origin restrictions even to a correctly signed app.
There is no auto-update: replace the app when you download a newer release; your datasets are kept.

On first launch the app shows that it contains no data and offers **Import…**.

## Use

1. **Import…** (or `File → Import Dataset…`): choose the summary-statistics file; the layout
   is detected from its header (the REGENIE meta-analysis layout with per-cohort columns is
   built in, as is a long one-row-per-cohort layout). Optionally add the VEP annotation TSV,
   a name and the genome build, then *Start import*. Progress is live; the original files are
   never modified.
2. Browse: the home page lists genes; a gene page lists its variants with annotation columns
   and filters; a variant page shows annotation cards, a PheWAS Manhattan plot and the
   association table with one column group per cohort.
3. **Library**: switch between datasets, rename, export or remove them. **Dataset details**
   shows the manifest, source files with checksums, import warnings and the log.

Datasets live in `~/Library/Application Support/PheWAS Browser` (macOS) or
`%LOCALAPPDATA%\PheWAS Browser` (Windows) — `File → Show Data Folder`. This library is shared
by every copy of the app on the computer (including builds run from source), and survives
reinstalling or updating the app.

## Sharing datasets

A dataset is shared as a **`.phewasds` bundle** — one file holding the imported database, its
manifest (sources, checksums, cohorts, warnings, RUO notes) and the import log:

- **Library → Export…** next to a dataset (or `phewas export <file.phewasds> [dataset]`) writes
  the bundle. It is about the size of the imported database (≈ 3 GB for the IEI dataset).
- **Import… → Or import a dataset bundle** (or `phewas import-bundle <file.phewasds>`) loads it
  on another computer. The checksum is verified during extraction; a bundle written by a
  newer version of the app is refused with a message to update.
- The dataset keeps its id across machines, so collaborators can refer to the same one; the
  same bundle cannot be imported twice unless the copy is removed first.

Bundles carry RUO data: send them through an approved institutional channel. Never upload
study data, dataset bundles, import logs, or screenshots containing study results to this
public repository, its issues, or its releases.

## Command line (the same engine)

```bash
uv sync                                   # once; needs uv (https://docs.astral.sh/uv/)
uv run phewas import sumstats.tsv.gz --annotation vep.tsv --name "My study" --build GRCh38
uv run phewas list | info <id> | remove <id> | profiles
uv run phewas export study.phewasds            # bundle the current dataset (or give an id)
uv run phewas import-bundle study.phewasds     # load a bundle into the library
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
`.github/workflows/release.yml` for macOS (arm64 and Intel) and Windows; `docs/RELEASING.md`
covers signing, notarization and handing builds to collaborators.
