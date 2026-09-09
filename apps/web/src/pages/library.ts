/* Library: every imported dataset, with open / make current / rename / remove. */
import { api, watchJob } from "../api";
import { esc, fmtBytes, fmtDate, fmtNum } from "../format";
import { href } from "../router";
import { invalidateLibrary, loadLibrary, setActive } from "../state";
import { saveBundle } from "../components/filepicker";

export async function renderLibrary($app: HTMLElement): Promise<void> {
  const lib = await loadLibrary(true);
  if (!$app.isConnected) return;
  setActive(null);
  if (!lib.datasets.length) {
    $app.innerHTML = `
      <h1>Welcome</h1>
      <div class="empty">
        <p><b>This application contains no data.</b> Datasets you import are stored on this computer only, in
          <span class="mono">${esc(lib.home)}</span>, and never leave it.</p>
        <p>Start with a summary-statistics file (REGENIE meta-analysis or long layout, plus optional VEP
          annotation), or with a <span class="mono">.phewasds</span> bundle exported from another PheWAS Browser.</p>
        <p><a class="button primary" href="${href.import()}">Import a dataset…</a></p>
        <p class="note">Research Use Only — datasets carry their own data-use notes; do not disseminate them.</p>
      </div>`;
    return;
  }
  $app.innerHTML = `
    <h1>Library</h1>
    <div class="subtitle">${lib.datasets.length} dataset${lib.datasets.length === 1 ? "" : "s"} in
      <span class="mono">${esc(lib.home)}</span>. <a href="${href.import()}">Import another…</a></div>
    <div class="ds-list">
      ${lib.datasets.map((d) => `
        <div class="ds-card ${d.id === lib.current ? "current" : ""}" data-id="${esc(d.id)}">
          <div class="ds-head">
            <a class="ds-name" href="${href.home(d.id)}">${esc(d.name)}</a>
            ${d.id === lib.current ? '<span class="pill">current</span>' : ""}
            <span class="dim mono">${esc(d.id)}</span>
          </div>
          <div class="ds-meta">
            ${fmtNum(d.stats["n_genes"])} genes · ${fmtNum(d.stats["n_variants"])} variants ·
            ${fmtNum(d.stats["n_traits"])} phenotypes · ${fmtNum(d.stats["n_assoc"])} associations ·
            cohorts ${d.cohorts.map((c) => esc(c.id)).join(" / ")} · ${esc(d.dictionary.label)}
            ${d.build ? ` · ${esc(d.build)}` : ""} · ${fmtBytes(d.size_bytes)} · imported ${esc(fmtDate(d.created))}
          </div>
          ${d.warnings.length ? `<div class="ds-warn">${d.warnings.length} import warning${d.warnings.length > 1 ? "s" : ""} — see details</div>` : ""}
          <div class="ds-actions">
            <a class="button" href="${href.home(d.id)}">Open</a>
            <a class="button" href="${href.info(d.id)}">Details</a>
            ${d.id !== lib.current ? `<button data-act="current">Make current</button>` : ""}
            <button data-act="rename">Rename</button>
            <button data-act="export">Export…</button>
            <button data-act="remove" class="danger">Remove…</button>
            <span class="note ds-status"></span>
          </div>
        </div>`).join("")}
    </div>`;

  $app.querySelectorAll<HTMLElement>(".ds-card").forEach((card) => {
    const id = card.dataset.id!;
    const entry = lib.datasets.find((d) => d.id === id)!;
    card.querySelectorAll<HTMLButtonElement>("button[data-act]").forEach((btn) => {
      btn.onclick = async () => {
        try {
          if (btn.dataset.act === "current") {
            await api.setCurrent(id);
          } else if (btn.dataset.act === "rename") {
            const name = prompt("Dataset name", entry.name);
            if (!name || name.trim() === entry.name) return;
            await api.patchDataset(id, { name: name.trim() });
          } else if (btn.dataset.act === "export") {
            saveBundle(`${entry.name.replace(/[^\w.-]+/g, "_")}.phewasds`, (path) => void exportTo(card, id, path));
            return;
          } else if (btn.dataset.act === "remove") {
            if (!confirm(`Remove "${entry.name}" (${fmtBytes(entry.size_bytes)}) from disk? This cannot be undone.`)) return;
            await api.deleteDataset(id);
          }
          invalidateLibrary();
          await renderLibrary($app);
        } catch (e) {
          alert((e as Error).message);
        }
      };
    });
  });
}


async function exportTo(card: HTMLElement, id: string, path: string): Promise<void> {
  const status = card.querySelector<HTMLElement>(".ds-status")!;
  const buttons = card.querySelectorAll<HTMLButtonElement>("button");
  buttons.forEach((b) => (b.disabled = true));
  try {
    const job = await api.exportDataset(id, path);
    const final = await watchJob(job.id, (j) => {
      if (!status.isConnected) return;
      const pct = j.total > 1 ? ` ${Math.round((100 * j.done) / j.total)}%` : "";
      status.textContent = j.step === "hash" ? `Checksumming…${pct}` : `Exporting…${pct}`;
    });
    if (!status.isConnected) return;
    if (final.status === "done" && final.result?.path) {
      status.innerHTML = `Exported to <span class="mono">${esc(final.result.path)}</span> (${fmtBytes(final.result.bytes)})`;
    } else {
      status.textContent = final.status === "cancelled" ? "Export cancelled." : `Export failed: ${final.error ?? "unknown error"}`;
    }
  } catch (e) {
    if (status.isConnected) status.textContent = (e as Error).message;
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}