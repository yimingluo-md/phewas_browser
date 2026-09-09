/* Import wizard: files -> detected layout & validation -> live progress -> open the dataset. */
import { api, watchJob } from "../api";
import { esc, fmtBytes, fmtNum } from "../format";
import { href } from "../router";
import { invalidateLibrary } from "../state";
import type { InspectAnnotation, InspectBundle, InspectSumstats, Job } from "../types";
import { pickFile } from "../components/filepicker";
import { el, val } from "../components/table";

const STEPS: [string, string][] = [
  ["sniff", "Reading the header"], ["dictionary", "Loading the phenotype dictionary"],
  ["stage", "Reading and sorting the summary statistics"], ["assoc", "Building associations"],
  ["annotation", "Importing annotation"], ["derive", "Deriving gene and variant summaries"],
  ["finalize", "Hashing sources and writing the manifest"], ["hash", "Hashing sources"], ["done", "Done"],
];
const BUNDLE_STEPS: [string, string][] = [
  ["extract", "Extracting and verifying the bundle"], ["done", "Done"],
];

export async function renderImport($app: HTMLElement, signal?: AbortSignal): Promise<void> {
  // a job already running (e.g. after a reload) takes over the page
  const running = (await api.jobs()).find((j) => j.status === "queued" || j.status === "running");
  if (!$app.isConnected || signal?.aborted) return;
  if (running) { renderProgress($app, running, signal); return; }

  const [profiles, dictionaries] = await Promise.all([api.profiles(), api.dictionaries()]);
  if (!$app.isConnected || signal?.aborted) return;
  $app.innerHTML = `
    <h1>Import a dataset</h1>
    <div class="subtitle">Point at a summary-statistics file (and optionally its VEP annotation). The layout is
      detected from the header; nothing is written until you start the import, and the original files are never modified.</div>
    <div class="panel wizard">
      <div class="form-row">
        <label for="i-sumstats">Summary statistics <span class="req">required</span></label>
        <div class="path-row"><input id="i-sumstats" type="text" spellcheck="false" placeholder="/path/to/sumstats.tsv.gz">
          <button id="b-sumstats">Browse…</button></div>
        <div id="d-sumstats" class="detect"></div>
      </div>
      <div class="form-row">
        <label for="i-annotation">Variant annotation (VEP TSV) <span class="dim">optional</span></label>
        <div class="path-row"><input id="i-annotation" type="text" spellcheck="false" placeholder="/path/to/annotation.vep.tsv">
          <button id="b-annotation">Browse…</button></div>
        <div id="d-annotation" class="detect"></div>
      </div>
      <div class="form-grid">
        <label>Name<input id="i-name" type="text" placeholder="e.g. IEI AoU+UKBB meta v9"></label>
        <label>Genome build<input id="i-build" type="text" placeholder="e.g. GRCh38" size="10"></label>
        <label>Phenotype dictionary<select id="i-dict">
          ${dictionaries.map((d) => `<option value="${esc(d.id)}">${esc(d.label)}</option>`).join("")}
          <option value="__custom">Custom CSV (trait, description, …)…</option></select></label>
        <label>Layout profile<select id="i-profile"><option value="">auto-detect</option>
          ${profiles.map((p) => `<option value="${esc(p.name)}">${esc(p.label)}</option>`).join("")}</select></label>
        <label class="wide">Notes / data-use statement<input id="i-notes" type="text" value="Research Use Only — do not disseminate."></label>
        <label class="chk"><input id="i-current" type="checkbox" checked> make it the current dataset</label>
      </div>
      <div id="i-custom-dict" class="form-row hidden">
        <label for="i-dictpath">Dictionary CSV</label>
        <div class="path-row"><input id="i-dictpath" type="text" spellcheck="false"><button id="b-dictpath">Browse…</button></div>
      </div>
      <div class="form-actions">
        <button id="i-start" class="primary" disabled>Start import</button>
        <span id="i-hint" class="note">Choose a summary-statistics file to continue.</span>
      </div>
    </div>
    <h2>Or import a dataset bundle</h2>
    <div class="subtitle">A <span class="mono">.phewasds</span> file exported from another PheWAS Browser
      (Library → Export…) contains a ready-made dataset; nothing is recomputed.</div>
    <div class="panel wizard">
      <div class="form-row">
        <label for="b-path">Dataset bundle</label>
        <div class="path-row"><input id="b-path" type="text" spellcheck="false" placeholder="/path/to/dataset.phewasds">
          <button id="b-browse">Browse…</button></div>
        <div id="d-bundle" class="detect"></div>
      </div>
      <div class="form-grid">
        <label>Name <span class="dim">(optional, keeps the bundle's name if empty)</span><input id="b-name" type="text"></label>
        <label class="chk"><input id="b-current" type="checkbox" checked> make it the current dataset</label>
      </div>
      <div class="form-actions">
        <button id="b-start" class="primary" disabled>Import bundle</button>
        <span id="b-hint" class="note">Choose a bundle to continue.</span>
      </div>
    </div>`;

  const form = el("i-sumstats");
  const formActive = () => form.isConnected && !signal?.aborted;
  const bind = (input: string, button: string, after: () => void, dirty: () => void) => {
    el<HTMLButtonElement>(button).onclick = () => pickFile(val(input) ? val(input).replace(/[\\/][^\\/]*$/, "") : undefined,
      (p) => { if (formActive()) { el<HTMLInputElement>(input).value = p; dirty(); after(); } });
    let t: number | undefined;
    el(input).addEventListener("input", () => { dirty(); clearTimeout(t); t = window.setTimeout(after, 400); });
    el(input).addEventListener("change", after);
  };
  let sumOk = false;
  let annOk = true;
  const refreshStart = () => {
    if (!formActive()) return;
    el<HTMLButtonElement>("i-start").disabled = !(sumOk && annOk);
    el("i-hint").textContent = !val("i-sumstats") ? "Choose a summary-statistics file to continue."
      : !sumOk ? "Fix the problems above to continue." : !annOk ? "Fix the annotation file or clear the field." : "Ready.";
  };
  const inspectSum = async () => {
    if (!formActive()) return;
    const path = val("i-sumstats").trim();
    const profile = val("i-profile");
    const current = () => formActive() && path === val("i-sumstats").trim() && profile === val("i-profile");
    const $d = el("d-sumstats");
    sumOk = false;
    refreshStart();
    if (!path) { $d.innerHTML = ""; sumOk = false; refreshStart(); return; }
    $d.innerHTML = '<div class="loading">Inspecting…</div>';
    try {
      const r = (await api.inspect({ sumstats: path, profile: profile || undefined })).sumstats!;
      if (!current()) return;
      $d.innerHTML = sumstatsHtml(r);
      sumOk = r.exists && r.problems.length === 0;
      if (!val("i-name")) el<HTMLInputElement>("i-name").value = path.split(/[\\/]/).pop()!.replace(/\.(tsv|txt|csv)(\.gz|\.bgz)?$/i, "");
    } catch (e) { if (!current()) return; $d.innerHTML = `<div class="error">${esc((e as Error).message)}</div>`; sumOk = false; }
    refreshStart();
  };
  const inspectAnn = async () => {
    if (!formActive()) return;
    const path = val("i-annotation").trim();
    const current = () => formActive() && path === val("i-annotation").trim();
    const $d = el("d-annotation");
    annOk = !path;
    refreshStart();
    if (!path) { $d.innerHTML = ""; annOk = true; refreshStart(); return; }
    $d.innerHTML = '<div class="loading">Inspecting…</div>';
    try {
      const r = (await api.inspect({ annotation: path })).annotation!;
      if (!current()) return;
      $d.innerHTML = annotationHtml(r);
      annOk = r.exists && r.problems.length === 0;
    } catch (e) { if (!current()) return; $d.innerHTML = `<div class="error">${esc((e as Error).message)}</div>`; annOk = false; }
    refreshStart();
  };
  bind("i-sumstats", "b-sumstats", () => void inspectSum(), () => { sumOk = false; refreshStart(); });
  bind("i-annotation", "b-annotation", () => void inspectAnn(), () => { annOk = !val("i-annotation").trim(); refreshStart(); });
  el("i-profile").addEventListener("change", () => void inspectSum());
  el("i-dict").addEventListener("change", () => el("i-custom-dict").classList.toggle("hidden", val("i-dict") !== "__custom"));
  el<HTMLButtonElement>("b-dictpath").onclick = () => pickFile(undefined, (p) => { if (formActive()) el<HTMLInputElement>("i-dictpath").value = p; });

  el<HTMLButtonElement>("i-start").onclick = async () => {
    const dict = val("i-dict") === "__custom" ? val("i-dictpath").trim() : val("i-dict");
    if (!dict) { alert("Choose a dictionary CSV."); return; }
    el<HTMLButtonElement>("i-start").disabled = true;
    try {
      const job = await api.startImport({
        sumstats: val("i-sumstats").trim(), annotation: val("i-annotation").trim() || null,
        name: val("i-name").trim(), dictionary: dict, profile: val("i-profile") || null,
        build: val("i-build").trim() || null, notes: val("i-notes"),
        make_current: el<HTMLInputElement>("i-current").checked,
      });
      if (formActive()) renderProgress($app, job, signal);
    } catch (e) {
      if (!formActive()) return;
      alert((e as Error).message);
      el<HTMLButtonElement>("i-start").disabled = false;
    }
  };

  /* ---- bundle section ---- */
  let bundleOk = false;
  const refreshBundle = () => {
    if (!formActive()) return;
    el<HTMLButtonElement>("b-start").disabled = !bundleOk;
    el("b-hint").textContent = !val("b-path") ? "Choose a bundle to continue." : bundleOk ? "Ready." : "Fix the problems above to continue.";
  };
  const inspectBundle = async () => {
    if (!formActive()) return;
    const path = val("b-path").trim();
    const current = () => formActive() && path === val("b-path").trim();
    const $d = el("d-bundle");
    bundleOk = false;
    refreshBundle();
    if (!path) { $d.innerHTML = ""; return; }
    $d.innerHTML = '<div class="loading">Inspecting…</div>';
    try {
      const r = await api.inspectBundle(path);
      if (!current()) return;
      $d.innerHTML = bundleHtml(r);
      bundleOk = r.exists && r.problems.length === 0;
    } catch (e) { if (!current()) return; $d.innerHTML = `<div class="error">${esc((e as Error).message)}</div>`; }
    refreshBundle();
  };
  el<HTMLButtonElement>("b-browse").onclick = () => pickFile(val("b-path") ? val("b-path").replace(/[\\/][^\\/]*$/, "") : undefined,
    (p) => { if (formActive()) { el<HTMLInputElement>("b-path").value = p; void inspectBundle(); } }, "bundle");
  let bt: number | undefined;
  el("b-path").addEventListener("input", () => { bundleOk = false; refreshBundle(); clearTimeout(bt); bt = window.setTimeout(() => void inspectBundle(), 400); });
  el("b-path").addEventListener("change", () => void inspectBundle());
  el<HTMLButtonElement>("b-start").onclick = async () => {
    el<HTMLButtonElement>("b-start").disabled = true;
    try {
      const job = await api.importBundle({ path: val("b-path").trim(), name: val("b-name").trim() || null,
        make_current: el<HTMLInputElement>("b-current").checked });
      if (formActive()) renderProgress($app, job, signal);
    } catch (e) {
      if (!formActive()) return;
      alert((e as Error).message);
      el<HTMLButtonElement>("b-start").disabled = false;
    }
  };
}

function bundleHtml(r: InspectBundle): string {
  if (!r.exists) return `<div class="problem">File not found.</div>`;
  if (!r.dataset_id) return r.problems.map((p) => `<div class="problem">${esc(p)}</div>`).join("");
  const s = r.stats ?? {};
  return `
    <div class="detect-row"><b>${esc(r.name ?? "")}</b> · ${fmtBytes(r.bytes)} · exported ${esc(r.created ?? "?")}
      ${r.build ? ` · ${esc(r.build)}` : ""}${r.dictionary ? ` · ${esc(r.dictionary.label)}` : ""}</div>
    <div class="detect-row">${fmtNum(s["n_genes"])} genes · ${fmtNum(s["n_variants"])} variants · ${fmtNum(s["n_traits"])} phenotypes ·
      cohorts ${(r.cohorts ?? []).map((c) => `<span class="pill ${c.is_meta ? "meta" : ""}">${esc(c.id)}</span>`).join(" ")}</div>
    ${r.notes ? `<div class="detect-row dim">${esc(r.notes)}</div>` : ""}
    ${r.problems.map((p) => `<div class="problem">${esc(p)}</div>`).join("")}`;
}

function sumstatsHtml(r: InspectSumstats): string {
  if (!r.exists) return `<div class="problem">File not found.</div>`;
  const cols = r.header ?? [];
  const preview = r.preview ?? [];
  const showCols = cols.slice(0, 12);
  return `
    <div class="detect-row"><b>${fmtBytes(r.bytes)}</b> · ${cols.length} columns ·
      ${r.profile ? `layout <b>${esc(r.profile_label)}</b> <span class="dim">(${esc(r.kind)})</span>` : "<b>layout not recognised</b>"}</div>
    ${r.cohorts?.length ? `<div class="detect-row">Cohorts: ${r.cohorts.map((c) =>
      `<span class="pill ${c.is_meta ? "meta" : ""}" title="${esc(c.statistics.join(", "))}">${esc(c.id)}${c.is_meta ? " (meta)" : ""} · ${c.statistics.length} stats</span>`).join(" ")}</div>` : ""}
    ${r.problems.map((p) => `<div class="problem">${esc(p)}</div>`).join("")}
    ${preview.length ? `<details><summary class="dim">first rows</summary><div class="tablewrap"><table class="preview">
      <thead><tr>${showCols.map((c) => `<th>${esc(c)}</th>`).join("")}${cols.length > 12 ? `<th class="dim">… ${cols.length - 12} more</th>` : ""}</tr></thead>
      <tbody>${preview.map((row) => `<tr>${showCols.map((c) => `<td>${esc(row[c] ?? "")}</td>`).join("")}${cols.length > 12 ? "<td></td>" : ""}</tr>`).join("")}</tbody>
    </table></div></details>` : ""}`;
}

function annotationHtml(r: InspectAnnotation): string {
  if (!r.exists) return `<div class="problem">File not found.</div>`;
  return `
    <div class="detect-row"><b>${fmtBytes(r.bytes)}</b> · ${r.header?.length ?? 0} columns ·
      ${r.fields_covered?.length ?? 0} of ${r.n_fields_total ?? 0} annotation fields available</div>
    ${r.problems.map((p) => `<div class="problem">${esc(p)}</div>`).join("")}`;
}

/* ---------------------------------------------------------------- progress */
function renderProgress($app: HTMLElement, job: Job, signal?: AbortSignal): void {
  const req = job.request as { sumstats?: string; annotation?: string | null; name?: string; bundle?: string };
  const isBundle = job.kind === "import-bundle";
  const steps = isBundle ? BUNDLE_STEPS : STEPS.filter(([k]) => k !== "hash" && (k !== "annotation" || req.annotation));
  $app.innerHTML = `
    <h1>Importing <span class="dim">${esc(req.name ?? "")}</span></h1>
    <div class="subtitle mono" style="font-size:12px">${esc(req.sumstats ?? req.bundle ?? "")}${req.annotation ? `<br>${esc(req.annotation)}` : ""}</div>
    <div class="panel">
      <ol class="steps" id="steps">${steps
        .map(([k, label]) => `<li data-step="${k}"><span class="step-label">${esc(label)}</span><span class="step-msg dim"></span></li>`).join("")}</ol>
      <div class="progress"><div class="bar" id="bar"></div></div>
      <div class="form-actions">
        <button id="cancel" class="danger">Cancel</button>
        <span id="status" class="note"></span>
      </div>
      <div id="result"></div>
    </div>`;
  const order = (isBundle ? BUNDLE_STEPS : STEPS).map(([k]) => k);
  const bar = el("bar"), status = el("status"), result = el("result");
  const cancel = el<HTMLButtonElement>("cancel");
  const update = (j: Job) => {
    if (!bar.isConnected) return;
    const step = j.step === "hash" ? "finalize" : j.step;
    const idx = order.indexOf(step);
    $app.querySelectorAll<HTMLElement>("#steps li").forEach((li) => {
      const i = order.indexOf(li.dataset.step!);
      li.classList.toggle("done", j.status === "done" || i < idx);
      li.classList.toggle("active", i === idx && j.status === "running");
      if (i === idx) li.querySelector(".step-msg")!.textContent = j.status === "done" && step === "done" ? ""
        : j.total > 1 ? (isBundle ? `${fmtBytes(j.done)} / ${fmtBytes(j.total)}` : `${fmtNum(j.done)} / ${fmtNum(j.total)} · ${j.message}`) : j.message;
    });
    const frac = j.status === "done" ? 1 : j.total > 1 ? j.done / j.total : idx >= 0 ? idx / order.length : 0;
    bar.style.width = `${Math.round(frac * 100)}%`;
    status.textContent = j.status === "running" ? "running…" : j.status;
  };
  update(job);
  cancel.onclick = async () => {
    if (!confirm("Cancel this import? Nothing will be kept.")) return;
    try { await api.cancelJob(job.id); } catch (e) { if (status.isConnected) status.textContent = (e as Error).message; }
  };
  watchJob(job.id, update, 0, signal).then((final) => {
    if (!bar.isConnected) return;
    update(final);
    cancel.disabled = true;
    invalidateLibrary();
    const $r = result;
    if (final.status === "done" && final.result) {
      const s = final.result.stats ?? {};
      $r.innerHTML = `<div class="success">Imported <b>${esc(final.result.name)}</b> in ${final.result.seconds}s:
          ${fmtNum(s["n_genes"])} genes, ${fmtNum(s["n_variants"])} variants, ${fmtNum(s["n_traits"])} phenotypes,
          ${fmtNum(s["n_assoc"])} associations.</div>
        ${final.warnings.length ? `<ul class="warnings">${final.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
        <div class="form-actions"><a class="button primary" href="${href.home(final.result.dataset_id)}">Open the dataset</a>
          <a class="button" href="${href.library()}">Library</a></div>`;
    } else if (final.status === "cancelled") {
      $r.innerHTML = '<div class="note">Import cancelled. <button id="again">Start again</button></div>';
      el<HTMLButtonElement>("again").onclick = () => void renderImport($app, signal);
    } else {
      $r.innerHTML = `<div class="error"><b>Import failed:</b> ${esc(final.error ?? "unknown error")}</div>
        <pre class="log">${esc(final.message)}</pre>
        <div class="form-actions"><button id="again">Back to the form</button></div>`;
      el<HTMLButtonElement>("again").onclick = () => void renderImport($app, signal);
    }
  }).catch((e) => { if (status.isConnected && !signal?.aborted) status.textContent = (e as Error).message; });
}
