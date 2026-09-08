/* Library: every imported dataset, with open / make current / rename / remove. */
import { api } from "../api";
import { esc, fmtBytes, fmtDate, fmtNum } from "../format";
import { href } from "../router";
import { invalidateLibrary, loadLibrary, setActive } from "../state";

export async function renderLibrary($app: HTMLElement): Promise<void> {
  const lib = await loadLibrary(true);
  if (!$app.isConnected) return;
  setActive(null);
  if (!lib.datasets.length) {
    $app.innerHTML = `
      <h1>Library</h1>
      <div class="empty">
        <p>No datasets yet. Import a summary-statistics file to start browsing.</p>
        <p><a class="button primary" href="${href.import()}">Import a dataset…</a></p>
        <p class="note">Datasets are stored in <span class="mono">${esc(lib.home)}</span>.</p>
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
            <button data-act="remove" class="danger">Remove…</button>
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
