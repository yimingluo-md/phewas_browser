/* Sortable, paged table helpers and CSV export (framework-free). */
import { esc } from "../format";

export interface SortState { key: string; dir: 1 | -1; page: number; per: number }

export function sortRows<T extends Record<string, unknown>>(rows: T[], key: string, dir: 1 | -1, numeric: boolean): T[] {
  return rows.slice().sort((a, b) => {
    const x = a[key], y = b[key];
    const xn = x === null || x === undefined, yn = y === null || y === undefined;
    if (xn && yn) return 0;
    if (xn) return 1;
    if (yn) return -1;
    if (numeric) return dir * (Number(x) - Number(y));
    return dir * String(x).localeCompare(String(y));
  });
}

export function headerCell(label: string, key: string, numeric: boolean, state: SortState, extra = ""): string {
  const arrow = state.key === key ? `<span class="arrow">${state.dir > 0 ? "▲" : "▼"}</span>` : "";
  return `<th data-key="${esc(key)}" data-num="${numeric ? 1 : 0}" class="${numeric ? "num" : ""} ${extra}">${label} ${arrow}</th>`;
}

/** Wire a <thead> for click-to-sort; `numeric` says which keys sort numerically. */
export function bindSort(thead: HTMLElement, state: SortState, numeric: Set<string>, redraw: () => void): void {
  thead.addEventListener("click", (e) => {
    const th = (e.target as HTMLElement).closest<HTMLElement>("th[data-key]");
    if (!th) return;
    const key = th.dataset.key ?? "";
    state.dir = state.key === key ? (state.dir === 1 ? -1 : 1) : 1;
    state.key = key;
    void numeric;
    redraw();
  });
}

export function pagerHtml(prefix: string, extra = ""): string {
  return `<div class="pager">
    <button id="${prefix}-prev">&larr; Prev</button>
    <span id="${prefix}-info"></span>
    <button id="${prefix}-next">Next &rarr;</button>
    ${extra}
  </div>`;
}

export function bindPager(prefix: string, state: SortState, redraw: () => void): void {
  document.getElementById(`${prefix}-prev`)!.onclick = () => { state.page--; redraw(); };
  document.getElementById(`${prefix}-next`)!.onclick = () => { state.page++; redraw(); };
}

export function updatePager(prefix: string, state: SortState, nRows: number): void {
  const npages = Math.max(1, Math.ceil(nRows / state.per));
  state.page = Math.min(state.page, npages - 1);
  document.getElementById(`${prefix}-info`)!.textContent = `page ${state.page + 1} / ${npages}`;
  (document.getElementById(`${prefix}-prev`) as HTMLButtonElement).disabled = state.page === 0;
  (document.getElementById(`${prefix}-next`) as HTMLButtonElement).disabled = state.page >= npages - 1;
}

export function downloadCSV(filename: string, cols: string[], rows: Record<string, unknown>[], headers?: string[]): void {
  const escCsv = (v: unknown) => {
    if (v === null || v === undefined) return "";
    const s = Array.isArray(v) ? v.join("+") : String(v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const lines = [(headers ?? cols).join(",")];
  rows.forEach((r) => lines.push(cols.map((c) => escCsv(r[c])).join(",")));
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

export const el = <T extends HTMLElement = HTMLElement>(id: string): T => document.getElementById(id) as T;
export const val = (id: string): string => (el<HTMLInputElement>(id)).value;
export const checked = (id: string): boolean => (el<HTMLInputElement>(id)).checked;
