/* A minimal server-side file picker (the native dialog arrives with the desktop shell in Phase 3). */
import { api } from "../api";
import { esc, fmtBytes } from "../format";

export function pickFile(start: string | undefined, onPick: (path: string) => void): void {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `<div class="modal">
    <div class="modal-head">
      <div class="crumbs" id="fp-crumbs"></div>
      <input id="fp-path" type="text" spellcheck="false">
      <button id="fp-go" class="small">Go</button>
      <button id="fp-close" class="small">Close</button>
    </div>
    <div class="fp-list" id="fp-list"><div class="loading">Loading…</div></div>
    <div class="note">Showing folders and .tsv / .csv / .txt / .gz / .bgz files. Click a file to choose it.</div>
  </div>`;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  (overlay.querySelector("#fp-close") as HTMLButtonElement).onclick = close;
  const $list = overlay.querySelector("#fp-list") as HTMLElement;
  const $path = overlay.querySelector("#fp-path") as HTMLInputElement;
  const $crumbs = overlay.querySelector("#fp-crumbs") as HTMLElement;

  const load = async (path?: string) => {
    $list.innerHTML = '<div class="loading">Loading…</div>';
    try {
      const d = await api.fs(path);
      $path.value = d.path;
      $crumbs.innerHTML = d.roots.map((r) => `<a href="#" data-dir="${esc(r)}">${esc(r === "/Volumes" ? "Volumes" : "Home")}</a>`).join(" · ")
        + (d.parent ? ` · <a href="#" data-dir="${esc(d.parent)}">&uarr; up</a>` : "");
      $list.innerHTML = d.entries.length ? d.entries.map((e) => `
        <div class="fp-entry ${e.is_dir ? "dir" : "file"}" data-path="${esc(e.path)}" data-dir="${e.is_dir ? 1 : 0}">
          <span class="fp-icon">${e.is_dir ? "&#128193;" : "&#128196;"}</span>
          <span class="fp-name">${esc(e.name)}</span>
          <span class="dim">${e.is_dir ? "" : fmtBytes(e.size)}</span>
        </div>`).join("") : '<div class="dim" style="padding:12px">Empty folder (or no data files)</div>';
    } catch (e) {
      $list.innerHTML = `<div class="error">${esc((e as Error).message)}</div>`;
    }
  };
  overlay.addEventListener("click", (e) => {
    const a = (e.target as HTMLElement).closest<HTMLElement>("a[data-dir]");
    if (a) { e.preventDefault(); void load(a.dataset.dir); return; }
    const row = (e.target as HTMLElement).closest<HTMLElement>(".fp-entry");
    if (!row) return;
    if (row.dataset.dir === "1") void load(row.dataset.path);
    else { onPick(row.dataset.path!); close(); }
  });
  (overlay.querySelector("#fp-go") as HTMLButtonElement).onclick = () => void load($path.value);
  $path.addEventListener("keydown", (e) => { if (e.key === "Enter") void load($path.value); });
  void load(start);
}
