/* Dataset details: manifest, cohorts, sources with hashes, warnings, import log. */
import { api } from "../api";
import { esc, fmtBytes, fmtDate, fmtNum } from "../format";
import { href } from "../router";
import { invalidateLibrary, loadLibrary } from "../state";

export async function renderInfo($app: HTMLElement, ds: string): Promise<void> {
  const info = await api.dataset(ds);
  if (!$app.isConnected) return;
  const m = info.manifest;
  if (!m) { $app.innerHTML = `<div class="error">No manifest for ${esc(ds)}</div>`; return; }
  const groups = new Map<string, number>();
  info.fields.filter((f) => !f.structural).forEach((f) => groups.set(f.group, (groups.get(f.group) ?? 0) + 1));
  $app.innerHTML = `
    <h1>${esc(m.name)} <span class="dim" style="font-size:14px;font-weight:400">details</span></h1>
    <div class="subtitle"><a href="${href.home(ds)}">&larr; back to the dataset</a> · <a href="${href.library()}">Library</a></div>
    <div class="annot-grid">
      <div class="annot-card"><h3>Dataset</h3><dl>
        <dt>Name</dt><dd>${esc(m.name)} <button id="rename" class="small">rename</button></dd>
        <dt>Id</dt><dd class="mono">${esc(m.id)}</dd>
        <dt>Imported</dt><dd>${esc(fmtDate(m.created))}</dd>
        <dt>Genome build</dt><dd>${esc(m.build ?? "–")}</dd>
        <dt>Phenotypes</dt><dd>${esc(m.dictionary.label)}</dd>
        <dt>Software</dt><dd>phewas_core ${esc(m.app_version)} · DuckDB ${esc(m.duckdb_version)} · schema v${m.schema_version}</dd>
        <dt>Location</dt><dd class="mono" style="font-size:11px">${esc(info.dir)}</dd>
        <dt>Notes</dt><dd>${esc(m.notes || "–")} <button id="notes" class="small">edit</button></dd>
      </dl></div>
      <div class="annot-card"><h3>Contents</h3><dl>
        <dt>Genes</dt><dd>${fmtNum(m.stats["n_genes"])}</dd>
        <dt>Variants</dt><dd>${fmtNum(m.stats["n_variants"])}</dd>
        <dt>Phenotypes</dt><dd>${fmtNum(m.stats["n_traits"])}</dd>
        <dt>Associations</dt><dd>${fmtNum(m.stats["n_assoc"])} <span class="dim">(${fmtNum(m.stats["n_assoc_rows"])} rows over all cohorts)</span></dd>
        <dt>Annotated pairs</dt><dd>${fmtNum(m.stats["n_annotation"])}</dd>
        <dt>Statistics</dt><dd>${m.statistics.map((s) => `<span class="pill">${esc(s)}</span>`).join(" ")}</dd>
        <dt>Annotation fields</dt><dd>${m.annotation_fields.length
          ? [...groups.entries()].map(([g, n]) => `${esc(g)} (${n})`).join(", ") : "none"}</dd>
      </dl></div>
      <div class="annot-card"><h3>Cohorts</h3><dl>
        ${m.cohorts.map((c) => `<dt>${esc(c.id)}${c.primary ? ' <span class="pill">primary</span>' : ""}</dt>
          <dd>${esc(c.label)}${c.is_meta ? " · meta-analysis" : ""}</dd>`).join("")}
      </dl></div>
      <div class="annot-card"><h3>Sources</h3><dl>
        ${m.sources.map((s) => `<dt>${esc(s.role)}</dt>
          <dd><span class="mono" style="font-size:11px">${esc(s.path)}</span>
            ${s.bytes ? `<br><span class="dim">${fmtBytes(s.bytes)}${s.profile ? ` · profile ${esc(s.profile)}` : ""}</span>` : ""}
            ${s.sha256 ? `<br><span class="dim mono" style="font-size:10px">sha256 ${esc(s.sha256)}</span>` : ""}</dd>`).join("")}
      </dl></div>
      ${m.warnings.length ? `<div class="annot-card warn"><h3>Import warnings</h3><ul>
        ${m.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
    </div>
    <div class="panel" style="margin-top:16px">
      <h2 style="margin-top:0">Import log</h2>
      <pre class="log">${esc(info.log || "(no log)")}</pre>
    </div>`;

  const rerender = async () => { invalidateLibrary(); await loadLibrary(); await renderInfo($app, ds); };
  (document.getElementById("rename") as HTMLButtonElement).onclick = async () => {
    const name = prompt("Dataset name", m.name);
    if (name && name.trim() !== m.name) { await api.patchDataset(ds, { name: name.trim() }); await rerender(); }
  };
  (document.getElementById("notes") as HTMLButtonElement).onclick = async () => {
    const notes = prompt("Notes (shown in the footer, e.g. the data-use statement)", m.notes);
    if (notes !== null && notes !== m.notes) { await api.patchDataset(ds, { notes }); await rerender(); }
  };
}
