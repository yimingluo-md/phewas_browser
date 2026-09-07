# PheWAS Browser — Mac App Architecture & Migration Plan

*Status: proposal v1 · 2026-09-07 · author: Yiming Luo (drafted with Claude)*

## 0. Where we are

The current `phewas_browser` is a **data-bound local web app**: a FastAPI server (`app.py`, ~180 lines) reads one hard-wired DuckDB file (`data/phewas.duckdb`, 2.9 GB) and serves a vanilla-JS + Plotly frontend (`static/`, ~850 lines). A one-off script (`scripts/build_db.py`) turns two fixed input files (the IEI AoU+UKBB meta sumstats and a VEP TSV) into six tables. Distribution is a folder containing the code, a bundled CPython 3.12 (arm64 + x86_64, and a Windows one), the database, and an AppleScript applet that runs `launch.sh`, which starts uvicorn on port 8555 and opens Safari.

What works well and should be kept:

- **DuckDB as the storage/query engine.** Sub-second gene and variant pages over 68.8 M association rows with no server infrastructure. This stays the core.
- **The derived-table design** (`assoc` → `variant_index` → `gene_summary`, plus `rsid_map`). The home page, gene page and search never touch the big table. Keep this pattern.
- **The UI itself** — hash router, gene table with client-side filters/sort/CSV, variant page with annotation cards, Manhattan plot, association table with optional per-cohort columns. Users know it; the redesign keeps the screens and changes the plumbing under them.
- **Offline-first, no install, RUO posture.** Nothing leaves the machine.

What blocks the goals (import/update by the user, no bundled data, many datasets, more cohorts, maintainability):

| Limitation today | Where it lives |
|---|---|
| One dataset, one hard-coded path | `app.py` `DB = .../data/phewas.duckdb`; module-level connection |
| Input file paths and column names hard-coded to one run | `build_db.py` `SUMSTATS`, `ANNOTATION`, `SUMSTATS_TYPES` |
| Cohorts `AoU`, `UKBB`, `Meta` baked into schema, API and UI | `assoc` columns `or_aou/p_aou/…`, `app.js` `t-aou`/`t-ukbb` toggles and column lists |
| Annotation fields baked into SQL, API and UI (≈60 columns, 3 places each) | `build_db.py` `clean` CTE, `app.py` gene query, `app.js` variant cards |
| Phenotype dictionary fixed to phecode v1.2 | `phecode` table, `pheinfo.rda`, groupnum/color assumptions in Manhattan |
| No version/provenance information in the database | — |
| Server has no auth; any local process can query RUO data on :8555 | `app.py`, `launch.sh` |
| Frontend is one 680-line file, no build step, no tests | `static/app.js` |
| Distribution is a 3 GB zip with data + runtime + code; every code fix means re-shipping the data | `make_bundle.sh` |
| Gatekeeper "Open Anyway" dance (ad-hoc signature) | `make_bundle.sh` `codesign --sign -` |

## 1. Goals and non-goals

**Goals**

1. A signed, notarized **macOS app** (`PheWAS Browser.app`) that contains *no summary statistics*. First launch shows an empty library and an **Import** button.
2. **Import** a sumstats file (+ optional annotation file, + phenotype dictionary) into a local dataset; **update** it later from a new file; keep **several datasets** side by side and switch between them.
3. **Cohort-agnostic**: the number and names of cohorts (and which one is the meta-analysis) come from the imported file, not from code.
4. **Extensible**: adding an annotation field, a cohort statistic, a new input format, or a new page should each touch one well-defined place.
5. **Maintainable** by one scientist-developer: small, typed, tested modules; CI builds; reproducible runtimes; one command to release.
6. **Windows** keeps getting a working build from the same codebase.

**Non-goals (for now)**

- Multi-user server deployment, cloud sync, or any network feature beyond the app updater.
- Running association tests inside the app (it browses results; it does not compute them).
- Mobile.

## 2. Target architecture

```
┌──────────────────────────────── PheWAS Browser.app ─────────────────────────────────┐
│                                                                                      │
│  Tauri 2 shell (Rust, ~300 lines)                                                    │
│   • native window, menus (File ▸ Import Dataset…, Manage Datasets…, Export…)        │
│   • file-open dialogs, Application Support paths, Keychain, single-instance           │
│   • spawns sidecar, passes {port, token}; kills it on quit                            │
│   • tauri-plugin-updater (signed update manifest)                                    │
│         │ WebView (system WKWebView)          │ child process                        │
│         ▼                                     ▼                                       │
│  Frontend (Vite + TypeScript)         phewas-server sidecar (frozen Python 3.12)     │
│   • same screens as today              FastAPI on 127.0.0.1:<random>, bearer token   │
│   • renders columns from metadata      ┌───────────────────────────────────────┐    │
│     (cohorts, annotation fields)       │ phewas_core (pure Python package)     │    │
│   • dataset switcher, import wizard,   │  datasets/  registry + manifests      │    │
│     job progress                        │  importer/  profiles, readers, jobs   │    │
│         │ fetch /api/... + Authorization│  schema/    canonical DDL, migrations │    │
│         └──────────────────────────────►│  query/     gene/variant/search repo  │    │
│                                         │  annotation/ field registry           │    │
│                                         │  dictionaries/ phecode v1.2, X, custom│    │
│                                         └───────────────────────────────────────┘    │
│                                                        │ duckdb                       │
└────────────────────────────────────────────────────────┼─────────────────────────────┘
                                                         ▼
      ~/Library/Application Support/PheWAS Browser/
        registry.json
        datasets/<uuid>/manifest.json, dataset.duckdb, import.log, sources.sha256
        profiles/<name>.json          (user-saved import profiles)
        dictionaries/<name>.parquet   (imported phenotype dictionaries)
```

### 2.1 Why Tauri 2 + Python sidecar

- All the domain logic (DuckDB SQL, import cleaning, the MANE/canonical transcript pick, dbNSFP `&`-collapsing, popmax) already exists in Python and is the part that will keep changing. Rewriting it in Swift or Rust buys speed we do not need and loses the ability to run the same code as a CLI on a cluster.
- Tauri gives a real `.app`/`.dmg` with a 5–10 MB shell, system WebView (no bundled Chromium), first-class **codesign + notarization + updater** tooling, and `.msi`/`.exe` for Windows from the same config. The `externalBin`/sidecar mechanism exists precisely for this pattern.
- The frontend stays a web app, so today's UI code is reused nearly line for line, and the browser-tab fallback (open `http://127.0.0.1:<port>/?token=…` in Safari) remains available for debugging and for machines where the app is not installed.
- Cost: two extra toolchains (Rust + Node) at build time only; end users install nothing.

Alternatives considered: **pywebview + PyInstaller** (one language, but no updater, weak menu/dialog integration, heavier app, Windows packaging is DIY); **Swift/SwiftUI + DuckDB Swift** (best native feel, but drops Windows, and the import pipeline and annotation logic would have to be ported and maintained twice while the CLI stays in Python); **Electron** (bundles Chromium, 150 MB+, no advantage over Tauri here).

### 2.2 Storage: the dataset library

A **dataset** is a directory with a manifest and one DuckDB file. Datasets are immutable once built; "update" builds a new version next to it and swaps a pointer, so an interrupted import can never corrupt what the user was browsing.

```jsonc
// datasets/9f2c…/manifest.json
{
  "manifest_version": 1,
  "id": "9f2c…", "name": "IEI haploinsufficiency — AoU+UKBB meta v9",
  "created": "2026-09-08T14:02:11Z", "app_version": "1.0.0", "duckdb_version": "1.5.5",
  "schema_version": 3,
  "build": "GRCh38",
  "cohorts": [                      // order = display order; exactly one may be primary
    {"id": "META", "label": "Meta (AoU+UKBB)", "primary": true, "is_meta": true},
    {"id": "AoU",  "label": "All of Us"},
    {"id": "UKBB", "label": "UK Biobank"}
  ],
  "statistics": ["or", "p", "beta", "se", "cases", "case_carriers", "controls", "ctrl_carriers", "aaf", "mac"],
  "dictionary": {"id": "phecode-1.2", "label": "Phecode v1.2"},
  "annotation": {"profile": "vep-tsv", "fields": ["consequence", "impact", "cadd_phred", …]},
  "sources": [
    {"role": "sumstats", "path": "/…/meta_IEI_AoU_UKBB.tsv.gz", "sha256": "…", "rows": 70712345, "profile": "regenie-meta-wide"},
    {"role": "annotation", "path": "/…/IEI_pilot….tsv", "sha256": "…", "rows": 51230}
  ],
  "stats": {"n_genes": 50, "n_variants": 43257, "n_traits": 1715, "n_assoc": 68760000},
  "notes": "Research Use Only — do not disseminate."
}
```

`registry.json` lists dataset ids, display order, and which one was open last. Manifests are the single source of truth the UI reads for "what columns exist"; nothing about cohorts or fields is hard-coded downstream.

**Storing the cohorts.** Today the wide table has `or_meta, p_meta, …, or_ukbb, p_ukbb`. The canonical schema becomes **long over cohort**:

```sql
CREATE TABLE assoc (
  variant_id VARCHAR, gene VARCHAR, trait VARCHAR,
  cohort     VARCHAR,          -- 'META', 'AoU', 'UKBB', …
  beta DOUBLE, se DOUBLE, "or" DOUBLE, p DOUBLE,
  cases INTEGER, case_carriers INTEGER, controls INTEGER, ctrl_carriers INTEGER,
  aaf DOUBLE, mac DOUBLE
);   -- sorted (gene, variant_id, trait, cohort); ~3× rows, similar bytes after compression
CREATE TABLE cohort (id VARCHAR PRIMARY KEY, label VARCHAR, ord SMALLINT, is_meta BOOLEAN, is_primary BOOLEAN);
CREATE TABLE trait  (trait VARCHAR PRIMARY KEY, description VARCHAR, category VARCHAR, category_ord SMALLINT, color VARCHAR);
CREATE TABLE variant (variant_id, gene, chrom, pos, ref, alt, source_any, PRIMARY KEY(variant_id, gene));
CREATE TABLE annotation (variant_id, gene, field VARCHAR, value_num DOUBLE, value_str VARCHAR);  -- EAV, or one wide table generated from the field registry (see 2.4)
-- derived, computed on the primary cohort:
CREATE TABLE variant_index (variant_id, gene, n_traits, min_p, top_trait, top_or, n_carriers);
CREATE TABLE gene_summary  (gene, chrom, min_pos, max_pos, n_variants, min_p, top_variant, top_trait);
CREATE TABLE rsid_map      (rsid, variant_id, gene);
CREATE TABLE meta          (key VARCHAR, value JSON);   -- copy of the manifest for self-description
```

A variant page becomes `SELECT … FROM assoc WHERE variant_id=? AND gene=?` (≈1,700 × k rows) and the API pivots to `{trait, stats: {META: {...}, AoU: {...}}}`. Adding a fourth cohort or a `beta`/`se` column is then a manifest change, not a schema change. DuckDB's columnar compression keeps the long table close to today's size; the current 68.8 M-row wide table would be ~206 M long rows, which DuckDB handles comfortably on a laptop (benchmark this in Phase 1 with the real file; if it is too slow or large, the fallback is a `MAP(cohort → STRUCT(...))` column, which keeps the flexibility with one row per association).

### 2.3 Import pipeline

The importer is **profile-driven**. A profile is JSON describing how one file layout maps to the canonical schema. Two ship built-in (the current meta-analysis layout, and a plain long format), and the wizard can generate one from any header.

```jsonc
// profiles/regenie-meta-wide.json — matches meta_IEI_AoU_UKBB.tsv.gz exactly
{
  "profile_version": 1, "name": "REGENIE meta-analysis (wide per cohort)",
  "format": {"delimiter": "\t", "compression": "auto", "null": ["NA", ""]},
  "keys": {"variant_id": "Name", "gene": "Gene", "trait": "Trait", "source": "Source"},
  "variant_id_format": "chr:pos:ref:alt", "strip_chr_prefix": true,
  "cohort_columns": {                     // regex with named groups → (stat, cohort)
    "pattern": "^(?P<stat>OR|Pval|Beta|SE|Cases|CaseCarr|Controls|CtrlCarr|AAF|MAC)_(?P<cohort>[A-Za-z0-9]+)$",
    "stat_map": {"OR": "or", "Pval": "p", "Beta": "beta", "SE": "se", "Cases": "cases",
                 "CaseCarr": "case_carriers", "Controls": "controls", "CtrlCarr": "ctrl_carriers",
                 "AAF": "aaf", "MAC": "mac"}
  },
  "meta_columns": {                       // columns that belong to the synthetic META cohort
    "cohort_id": "META", "label": "Meta-analysis",
    "map": {"Meta_OR": "or", "Meta_Pval": "p", "Beta_Meta": "beta", "Z_Meta": "z",
            "Total_Cases": "cases", "Total_Case_Carriers": "case_carriers",
            "Total_Controls": "controls", "Total_Ctrl_Carriers": "ctrl_carriers"}
  },
  "trait_filter": "in_dictionary"         // drop traits without a description, as build_db.py does today
}
```

Import runs as a **job** inside the sidecar (thread + DuckDB connection of its own), reporting progress over `/api/jobs/{id}` (SSE). Steps, each a small function with a test:

1. **Sniff** header, delimiter, compression, row count estimate; match against known profiles; propose a mapping.
2. **Validate** (fast, on a 100k-row sample): required keys present, `variant_id` parses, `p` within (0, 1], every trait code resolves in the chosen dictionary (report how many don't).
3. **Stage**: `read_csv` with explicit types into a temp DuckDB (`temp_directory` on disk, `memory_limit` = 50 % of RAM), unpivot cohort columns into the long `assoc`, build `variant`, `trait`, `cohort`.
4. **Annotate** (optional, separately re-runnable): apply the annotation profile (the VEP-TSV logic from `build_db.py`: MANE > canonical > first, `multi_max`/`multi_pred`, gnomAD popmax) into `annotation`; join on `(variant_id, gene)`.
5. **Derive** `variant_index`, `gene_summary`, `rsid_map` on the primary cohort.
6. **Finalize**: `CHECKPOINT`, write manifest with source hashes and counts, move directory into place, update registry. Old version kept until the user deletes it ("Keep previous version" is on by default).

"**Update dataset**" is the same pipeline pointed at the existing manifest: the wizard pre-fills profile, dictionary and annotation source, hashes the new file, and skips steps whose inputs are unchanged (re-running annotation without re-reading 70 M sumstats rows, for instance).

The same code is exposed as a **CLI** (`phewas import --profile regenie-meta-wide --dictionary phecode-1.2 --annotation vep.tsv sumstats.tsv.gz`) so datasets can be built on a cluster and copied in, and so CI can build fixtures.

### 2.4 Annotation field registry

Today each annotation field is spelled in three places. Instead, one Python registry (later loadable from JSON so users can add fields without a release):

```python
Field("cadd_phred", type=NUM, label="CADD (phred)", group="Deleteriousness", fmt="score1",
      source={"vep-tsv": ["CADD_PHRED", "CADD_phred"]}, filter="min", table_col=True),
Field("alphamissense_pred", type=STR, label="AlphaMissense", group="Deleteriousness",
      source={"vep-tsv": {"col": "AlphaMissense_pred", "collapse": "distinct"}}),
Field("spliceai_max_ds", type=NUM, ..., derived="greatest(spliceai_ds_ag, …)"),
```

The importer uses `source` to build SQL; the API returns `fields` metadata with the dataset; the frontend renders variant cards, table columns, filters and CSV headers from it. Adding PromoterAI-v2 = one line.

### 2.5 API

Versioned, dataset-scoped, token-protected:

```
GET  /api/v1/health                          {app, version, status}
GET  /api/v1/datasets                        library (from manifests)
POST /api/v1/datasets/import                 start job {sumstats, annotation?, dictionary, profile?, name}
GET  /api/v1/jobs/{id}   (SSE /events)       progress, warnings, result
GET  /api/v1/datasets/{ds}/meta              manifest + cohorts + fields + gene_summary
GET  /api/v1/datasets/{ds}/search?q=
GET  /api/v1/datasets/{ds}/genes/{gene}
GET  /api/v1/datasets/{ds}/variants/{id}?gene=
GET  /api/v1/datasets/{ds}/variants/{id}/associations.csv   server-side export (full precision)
GET  /api/v1/profiles, /api/v1/dictionaries
```

Every request carries `Authorization: Bearer <token>`; the token is generated by the shell per launch and handed to both the sidecar (env var) and the WebView (injected). The port is random and bound to `127.0.0.1`. This closes the current gap where any local process can read RUO data from :8555.

### 2.6 Frontend

Keep the screens, change the foundation: **Vite + TypeScript**, ES modules (`api.ts`, `router.ts`, `format.ts`, `pages/home.ts`, `pages/gene.ts`, `pages/variant.ts`, `components/table.ts`, `plots/manhattan.ts`), Plotly as a dependency. Cohort columns and annotation fields render from metadata. New screens: **Library** (dataset cards, open/rename/delete/update), **Import wizard** (files → detected profile & mapping → validation → progress), **Dataset info** (manifest, sources, counts, RUO notice). A component framework (Svelte 5 is the natural fit: small, no virtual DOM, readable for non-frontend developers) is worth adopting when the wizard is built; the current template-string approach is fine for porting the three existing pages.

### 2.7 Packaging, signing, updates

- **Sidecar**: PyInstaller `--onedir` of `phewas_server` (FastAPI + uvicorn + duckdb ≈ 60–80 MB per architecture), shipped in `Contents/Resources/sidecar/`. Startup < 1 s (onefile would extract on every launch; avoid it). Reproducible from `requirements.lock.txt`, replacing `prepare_macos_runtime.sh`.
- **Architectures**: separate Apple Silicon and Intel builds (as today) rather than a universal binary — PyInstaller cannot emit universal2 unless every wheel is universal2, and DuckDB's are not. GitHub Actions matrix: `macos-14` (arm64), `macos-15-intel`, `windows-latest`. Tauri's `externalBin` naming (`phewas-server-aarch64-apple-darwin`, `…-x86_64-apple-darwin`, `…-x86_64-pc-windows-msvc.exe`) supports this directly.
- **Signing/notarization**: Developer ID Application certificate + `notarytool`, driven by Tauri's bundler from CI secrets (`APPLE_CERTIFICATE`, `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`). Hardened runtime with the entitlements the sidecar needs (`com.apple.security.cs.allow-unsigned-executable-memory` is *not* needed for CPython 3.12 + DuckDB wheels; verify in Phase 3). Result: double-click to open, no "Open Anyway".
- **Updater**: `tauri-plugin-updater` with a minisign-signed `latest.json`. Since the source repo is private and the updater fetches anonymously, publish releases to a small **public** `phewas-browser-releases` repo (or an institutional HTTPS path). The app contains no data, so its binaries are not RUO.
- **Windows**: same pipeline produces a signed-if-possible `.msi`/NSIS installer; the sidecar is PyInstaller on Windows. This replaces the `.bat` launchers.
- **Sizes**: DMG ≈ 90–110 MB per architecture. Datasets live in Application Support and are never inside the app.

### 2.8 Security and RUO

- Data at rest: DuckDB ≥ 1.4 supports AES-256-GCM database encryption (`ATTACH … (ENCRYPTION_KEY …)`). Offer **"Encrypt datasets"** with the key stored in the macOS Keychain (Windows Credential Manager) — off by default in v1, on by default once benchmarked.
- The RUO banner and the dataset's `notes` come from the manifest, so each dataset carries its own disclaimer.
- "Export dataset" produces a `.phewasds` bundle (manifest + duckdb) for hand-off between collaborators over institutional channels; "Import dataset bundle" installs it without re-running the pipeline. This is how collaborators without the source files get the IEI dataset.

### 2.9 Repository layout (monorepo)

```
phewas_browser/
├── apps/desktop/                 Tauri app: src-tauri/ (Rust), src/ (Vite+TS frontend), tauri.conf.json
├── packages/
│   ├── phewas_core/              importable Python package (no web deps): datasets, importer, schema, query, annotation, dictionaries
│   └── phewas_server/            FastAPI app + `phewas-server` entrypoint; PyInstaller spec
├── profiles/                     built-in import profiles (JSON)
├── dictionaries/                 phecode_definitions1.2.csv (public), loaders for phecodeX
├── tests/                        pytest (core + API), fixtures/ (synthetic 3-gene dataset generator), e2e/ (Playwright)
├── legacy/                       today's app.py, launch.sh, .bat, make_bundle.sh — kept runnable until Phase 3 ships
├── docs/                         this plan, ADRs (docs/adr/0001-tauri-sidecar.md …), user guide
├── .github/workflows/            ci.yml (ruff, mypy, pytest, vitest), release.yml (matrix build, sign, notarize, publish)
├── pyproject.toml (uv workspace), requirements.lock.txt, package.json, Cargo.toml
```

Conventions that keep it maintainable: `uv` for Python env/lock, `ruff` + `mypy --strict` on `phewas_core`, `pytest` fixtures built from a **synthetic generator** (no real data ever in the repo or CI), conventional commits + `CHANGELOG.md`, semantic versions shared by app, sidecar and `schema_version` migrations, and an `ADR` per architectural decision.

## 3. Phased roadmap

Each phase ends with something usable; the existing launchers keep working until Phase 3.

| Phase | Deliverable | Key work | Effort* |
|---|---|---|---|
| **0 — Foundations** (this week) | Private repo, CI running lint/tests on a synthetic fixture | Done today: git + `.gitignore`. Next: `pyproject.toml`, `uv`, `ruff`, pytest skeleton, synthetic dataset generator, `legacy/` move | 1–2 days |
| **1 — Core extraction** | `phewas import …` CLI builds a dataset directory from the *existing* files via the built-in profile; `app.py` serves whichever dataset is chosen. UI unchanged. | `phewas_core` package; long-format schema + migrations; dataset registry/manifest; importer job with progress; annotation field registry; ported query layer with tests. Benchmark long vs wide on the real 70 M-row file. | 1.5–2 wk |
| **2 — Multi-dataset web UI** | Library page, dataset switcher, import wizard (paths typed/pasted), progress, cohort-dynamic columns, field-driven variant page, token auth. Still launched via `launch.sh`. | Vite + TS migration of `app.js`; new API v1; SSE progress; validation report UI | 2 wk |
| **3 — Native shell** | Unsigned `PheWAS Browser.app` for arm64 + Intel and a Windows build, sidecar auto-start, native file dialogs and menus, Application Support storage, clean quit | Tauri project; PyInstaller sidecar; port/token handoff; single-instance; error surfaces (sidecar crash → dialog + log) | 1.5 wk |
| **4 — Distribution** | Signed + notarized DMG, MSI, GitHub Actions release pipeline, auto-update, user guide | Developer ID enrolment, CI secrets, updater keys, public releases repo, `.phewasds` export/import | 1 wk |
| **5 — Hardening & new features** | Encryption at rest; gene-level/burden results table; cross-dataset compare (same variant in v8 vs v9); region/locus view; saved filters; report export | Each feature = new `phewas_core` module + field/profile entries + one page | ongoing |

\*Effort is focused development time for one person familiar with the code; calendar time will be longer.

## 4. Decisions to confirm before Phase 1

1. **Long-format `assoc`** (recommended) vs `MAP` column vs keep-wide-with-metadata — decided by the Phase 1 benchmark.
2. **Dataset immutability + versioning** (recommended: keep previous version until user deletes) vs in-place replace.
3. **Frontend framework**: port as TypeScript modules first (recommended), adopt Svelte for the wizard/library screens.
4. **Public releases repo** for the updater vs institutional HTTPS host.
5. **Minimum macOS**: 12 (Monterey) lets us use current WKWebView features; 11 keeps parity with today's Intel runtime.

## 5. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Import of 70 M rows exhausts memory or takes > 5 min on a laptop | DuckDB `memory_limit`/`temp_directory`, streaming `read_csv`, pre-sort by gene; progress + cancel; CLI path for cluster builds; benchmark early (Phase 1) |
| DuckDB storage-format compatibility across versions | Pin `duckdb` in the lock file; record `duckdb_version` in manifest; forward-compat is guaranteed by DuckDB ≥ 1.0, and the app offers "re-index dataset" if a newer app can't open an old file |
| PyInstaller sidecar flagged by Gatekeeper/notarization | Sign every Mach-O inside the bundle (Tauri does this for `externalBin`; verify for onedir contents with `codesign --deep --strict`); test notarization in Phase 3 not 4 |
| Updater cannot reach private repo | Public releases repo containing only binaries |
| Two toolchains (Rust, Node) intimidate future maintainers | The Rust layer is < 300 lines and rarely changes; document "you only need Python to change import/query logic" in `CONTRIBUTING.md`; CI does all builds |
| Users' files have layouts we have not seen | Profile wizard with column-mapping UI; profiles are JSON and shareable; unknown columns are preserved as extra stats, not dropped |
| RUO data exposure via local HTTP | Random port, loopback only, per-launch bearer token, no CORS wildcard; optional encryption at rest |

## 6. Immediate next steps

1. Confirm the four decisions in §4 (or accept the recommendations).
2. Phase 0: add `pyproject.toml`, `uv.lock`, `ruff`, pytest, `tests/fixtures/make_synthetic.py`, `.github/workflows/ci.yml`; move today's launchers to `legacy/`.
3. Phase 1 spike (1 day): unpivot the real sumstats into the long schema with DuckDB and time the variant/gene queries — this settles decision §4.1 before any further code is written.
