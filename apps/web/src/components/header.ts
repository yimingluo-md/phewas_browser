/* Header: brand, dataset switcher, scoped search, navigation. Footer: RUO line from the manifest. */
import { api } from "../api";
import { esc } from "../format";
import { go, href } from "../router";
import { active, datasetEntry, getLibrary, onChange } from "../state";
import type { SearchResult } from "../types";

const $header = document.getElementById("header")!;
const $footer = document.getElementById("footer")!;

export function renderHeader(): void {
  const lib = getLibrary();
  const ds = active();
  const entry = datasetEntry(ds);
  const options = (lib?.datasets ?? []).map((d) =>
    `<option value="${esc(d.id)}" ${d.id === ds ? "selected" : ""}>${esc(d.name)}</option>`).join("");
  $header.innerHTML = `
    <a class="brand" href="${ds ? href.home(ds) : href.library()}">PheWAS<span>Browser</span></a>
    <div class="dsw">
      ${lib && lib.datasets.length
        ? `<select id="ds-switch" title="Dataset">${options}</select>`
        : `<span class="dim">no dataset loaded</span>`}
      ${entry ? `<a class="navlink" href="${href.info(entry.id)}" title="Dataset details">details</a>` : ""}
    </div>
    <span class="ruo-badge" title="Research Use Only — contains sensitive data; do not disseminate">RUO</span>
    <div class="searchwrap ${ds ? "" : "hidden"}">
      <input id="search" type="text" placeholder="Search gene (NFKB2), variant (10:102395634:C:A) or rsID…"
             autocomplete="off" spellcheck="false">
      <div id="search-results" class="search-results hidden"></div>
    </div>
    <nav>
      <a class="navlink" href="${href.library()}">Library</a>
      <a class="navlink primary" href="${href.import()}">Import…</a>
    </nav>`;
  const sw = document.getElementById("ds-switch") as HTMLSelectElement | null;
  if (sw) sw.onchange = () => go(href.home(sw.value));
  bindSearch();

  const notes = entry?.notes || "Research Use Only — contains sensitive data; do not disseminate.";
  const cohorts = entry ? entry.cohorts.map((c) => c.label).join(" + ") : "";
  const ruo = /research use only/i.test(notes) ? esc(notes) : `<b>Research Use Only.</b> ${esc(notes)}`;
  $footer.innerHTML = `
    <div class="ruo-line">${ruo}</div>
    <span>${entry ? `${esc(entry.name)} · ${esc(cohorts)} · ${esc(entry.dictionary.label)} · ` : ""}Developed by Yiming Luo</span>`;
}

onChange(renderHeader);

/* ---------------------------------------------------------------- search box */
let searchTimer: number | undefined;
let searchSel = -1;

function bindSearch(): void {
  const $search = document.getElementById("search") as HTMLInputElement | null;
  const $sres = document.getElementById("search-results");
  if (!$search || !$sres) return;

  const goTo = (r: SearchResult) => {
    const ds = active();
    if (!ds) return;
    $sres.classList.add("hidden");
    $search.value = "";
    go(r.type === "gene" ? href.gene(ds, r.id) : href.variant(ds, r.id, r.gene));
  };
  let results: SearchResult[] = [];

  $search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    const term = $search.value.trim();
    const ds = active();
    if (!term || !ds) { $sres.classList.add("hidden"); return; }
    searchTimer = window.setTimeout(async () => {
      try {
        results = (await api.search(ds, term)).results;
        searchSel = -1;
        $sres.innerHTML = results.length
          ? results.map((r, i) =>
            `<div data-i="${i}"><span class="stype">${r.type}</span>${esc(r.label)}</div>`).join("")
          : '<div class="dim">No matches</div>';
        $sres.classList.remove("hidden");
      } catch { /* ignore */ }
    }, 180);
  });
  $sres.addEventListener("mousedown", (e) => {
    const div = (e.target as HTMLElement).closest<HTMLElement>("div[data-i]");
    if (div) { const r = results[Number(div.dataset.i)]; if (r) goTo(r); }
  });
  $search.addEventListener("keydown", (e) => {
    const items = [...$sres.querySelectorAll<HTMLElement>("div[data-i]")];
    if (e.key === "ArrowDown") searchSel = Math.min(searchSel + 1, items.length - 1);
    else if (e.key === "ArrowUp") searchSel = Math.max(searchSel - 1, 0);
    else if (e.key === "Enter") { const r = results[searchSel >= 0 ? searchSel : 0]; if (r) goTo(r); return; }
    else if (e.key === "Escape") { $sres.classList.add("hidden"); return; }
    else return;
    items.forEach((d, i) => d.classList.toggle("active", i === searchSel));
  });
  document.addEventListener("click", (e) => {
    if (!(e.target as HTMLElement).closest(".searchwrap")) $sres.classList.add("hidden");
  });
}
