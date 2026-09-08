# IEI PheWAS Browser

Local web UI for browsing variant-level PheWAS summary statistics from the
IEI haploinsufficiency AoU + UKBB meta-analysis.

Developed by Yiming Luo. **Research Use Only — contains sensitive data; do not disseminate.**

## Quick start (no command line needed)

**Mac**: double-click **`IEI PheWAS Browser.app`**. It starts the server (if it
isn't running already) and opens <http://localhost:8555> in your browser. The
distributed Mac app contains native runtimes for Apple Silicon and Intel, so it
does not need Python, developer tools, administrator access, or internet. To
shut the server down, double-click **`Stop PheWAS Browser.command`**. In a source
checkout, **`Launch IEI PheWAS Browser.command`** is also available as a fallback.

**Windows**: double-click **`Launch PheWAS Browser (Windows).bat`**. Nothing
needs to be installed — a Python runtime is bundled in `windows/`. A minimized
"server" window stays open while you browse; close it (or double-click
**`Stop PheWAS Browser (Windows).bat`**) to stop.

The Mac app can be dragged to the Dock or a Desktop alias can be made
(right-click → Make Alias); it always works as long as this folder stays in place.

## Sending to collaborators

Run `./scripts/make_bundle.sh`. It writes two self-contained downloads to the
Desktop: `IEI_PheWAS_Browser_Mac.zip` and
`IEI_PheWAS_Browser_Windows.zip`. You can build only one with
`./scripts/make_bundle.sh mac` or `./scripts/make_bundle.sh windows`. Share the
appropriate file via a **secure institutional channel** (OneDrive/Globus, not
email): the data is Research Use Only and must not be disseminated.

Collaborator instructions:

- **Extract the zip completely first** (don't launch from inside the zip).
- **Mac**: double-click `IEI PheWAS Browser.app`. If macOS blocks it
  ("Apple could not verify…"), go to System Settings → Privacy & Security →
  scroll down → **Open Anyway** (older macOS: right-click the app → Open).
  No other installation or internet connection is needed. The app is
  self-contained so Gatekeeper's randomized launch location cannot separate it
  from `launch.sh` or the database.
- **Windows** (10/11): double-click `Launch PheWAS Browser (Windows).bat`.
  If SmartScreen warns, click **More info → Run anyway**. Fully offline,
  nothing is installed.

## Quick start (command line)

```bash
cd /Users/yluo/Work/PheWAS/IEI_haploinsufficiency/phewas_browser
./launch.sh
```

Then open <http://localhost:8555>.

## What's inside

| Path | Purpose |
|---|---|
| `data/phewas.duckdb` | All data, one DuckDB file (~3.1 GB) |
| `data/phecode_definitions1.2.csv` | Standard 1,817-phecode v1.2 definitions (from the PheWAS R package `pheinfo`) |
| `scripts/build_db.py` | One-time build script (rerun if sumstats/annotation change; ~90 s) |
| `app.py` | FastAPI backend (search / gene / variant endpoints) |
| `static/` | Frontend (vanilla JS + Plotly, no build step) |
| `macos/` | Bundled Python 3.12 runtimes and packages for Apple Silicon and Intel |
| `windows/` | Bundled Python 3.12 runtime + packages for Windows (no install needed) |
| `scripts/prepare_macos_runtime.sh` | Rebuilds the two pinned, offline Mac runtimes |
| `scripts/make_bundle.sh` | Creates separate self-contained Mac and Windows ZIPs |

## Data notes

- **Sources**: `01_variant_level_meta/meta_IEI_AoU_UKBB.tsv.gz` (70.7M rows) and
  `data/IEI_pilot_filtered_AoU_UKBB_V9.vep_50bpPTC.spliceAIfilled.tsv`.
- **Kept**: 68.76M associations = 43,257 variants × 50 genes × 1,715 phecodes.
  Trait codes with no phecode v1.2 description (50 codes) were dropped.
- **Stats kept per association**: aOR + P for Meta (main), AoU and UKBB (optional
  columns in the UI), plus total cases/controls and case/control **carrier** counts
  per cohort (no het/hom split exists in the sumstats).
- `Source` = which cohorts contributed. For single-cohort rows the Meta columns
  pass through that cohort's estimate.
- **Annotation**: one row per (variant, gene) — MANE Select transcript preferred,
  else VEP canonical. dbNSFP per-transcript values ("T&.&.&T") are collapsed:
  scores → max, predictions → distinct set.
- `gnomad_popmax_af/pop` are computed as the max across gnomAD exome+genome
  AFR/AMR/EAS/NFE/SAS AFs (bottlenecked pops excluded).
- **SpliceAI**: SNVs use precomputed scores (d=50); indels come from the Broad
  lookup API (d=500). Note: 160/161 Broad-lookup indels are labeled
  `BroadAPI_masked_d50` in the source annotation file — the UI displays d=500
  per the pipeline's actual query distance; verify the fill script label if in doubt.
- Gene-page search accepts protein notation in both forms (`Arg158Gln` or `R158Q`);
  1-letter HGVSp is also shown in tables and CSV exports (`hgvsp_short`).

## The new browser (Phase 2)

```bash
export PATH="$HOME/.local/bin:$PATH"   # uv, installed once with: curl -LsSf https://astral.sh/uv/install.sh | sh
cd ~/phewas_browser && uv sync
uv run phewas serve                     # starts the server on a random port and opens the UI
```

The frontend must be built once (`cd apps/web && npm ci && npm run build`; needs Node 22) —
`phewas serve` tells you if it is missing. Datasets are imported from the UI (**Import…**)
or from the command line, see below; several can be kept side by side and switched in the header.

## Importing a dataset from the command line

The `phewas` command builds a self-contained dataset from a sumstats file and stores it in
the dataset library (`~/Library/Application Support/PheWAS Browser`, override with
`$PHEWAS_HOME`). The layout is detected from the header; the current meta-analysis file
matches the built-in `regenie-meta-wide` profile.

```bash
uv run phewas import 01_variant_level_meta/meta_IEI_AoU_UKBB.tsv.gz \
    --annotation data/IEI_pilot_filtered_AoU_UKBB_V9.vep_50bpPTC.spliceAIfilled.tsv \
    --name "IEI AoU+UKBB meta v9" --build GRCh38
uv run phewas list                 # datasets in the library (* = current)
uv run phewas serve                # browse the current dataset on http://127.0.0.1:8555
uv run phewas import --help        # profiles, dictionaries, memory limit, ...
```

See `docs/ARCHITECTURE_PLAN.md` and `docs/adr/` for the design.

## Rebuild after data updates (legacy pipeline)

```bash
cd /Users/yluo/Work/PheWAS/IEI_haploinsufficiency/phewas_browser
./macos/python-arm64/bin/python3 scripts/build_db.py  # Apple Silicon Mac
```
