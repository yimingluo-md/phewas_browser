/* Formatting helpers shared by all pages (ported from the Phase-0 app.js, plus field-driven fmt). */
import type { FieldDef } from "./types";

export const esc = (s: unknown): string =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);

export const dash = '<span class="dim">–</span>';

const isNil = (x: unknown): x is null | undefined => x === null || x === undefined;

export function fmtP(p: number | null | undefined): string {
  if (isNil(p)) return dash;
  if (p === 0) return "&lt;1e-320";
  if (p < 1e-4) return p.toExponential(2);
  return p.toPrecision(3);
}
export function fmtOR(x: number | null | undefined): string {
  if (isNil(x)) return dash;
  if (x >= 100) return x.toFixed(0);
  return x.toFixed(2);
}
export function fmtAF(x: number | null | undefined): string {
  if (isNil(x)) return dash;
  if (x === 0) return "0";
  if (x < 1e-3) return x.toExponential(2);
  return x.toPrecision(3);
}
export function fmtNum(x: number | null | undefined): string {
  if (isNil(x)) return dash;
  return x.toLocaleString();
}
export function fmtScore(x: number | null | undefined, digits = 2): string {
  if (isNil(x)) return dash;
  return Number(x).toFixed(digits);
}
export function fmtBytes(n: number | null | undefined): string {
  if (isNil(n)) return dash;
  if (n < 1024) return `${n} B`;
  const u = ["KB", "MB", "GB", "TB"];
  let i = -1;
  let v = n;
  do { v /= 1024; i++; } while (v >= 1024 && i < u.length - 1);
  return `${v.toFixed(v < 10 ? 2 : 1)} ${u[i]}`;
}
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString();
}
export function hgvsClean(s: string | null | undefined): string | null {
  return s ? s.replace(/%3D/g, "=") : null;
}

/* 3-letter -> 1-letter protein notation: "ENSP…:p.Arg158Gln" -> "p.R158Q" */
const AA3TO1: Record<string, string> = { Ala: "A", Arg: "R", Asn: "N", Asp: "D", Cys: "C", Gln: "Q", Glu: "E",
  Gly: "G", His: "H", Ile: "I", Leu: "L", Lys: "K", Met: "M", Phe: "F", Pro: "P",
  Ser: "S", Thr: "T", Trp: "W", Tyr: "Y", Val: "V", Sec: "U", Pyl: "O", Ter: "*", Xaa: "X" };
const AA3_RE = /(Ala|Arg|Asn|Asp|Cys|Gln|Glu|Gly|His|Ile|Leu|Lys|Met|Phe|Pro|Ser|Thr|Trp|Tyr|Val|Sec|Pyl|Ter|Xaa)/g;
export function hgvspShort(hgvsp: string | null | undefined): string | null {
  if (!hgvsp) return null;
  let p = hgvsClean(hgvsp) ?? "";
  const i = p.indexOf(":p.");
  if (i >= 0) p = p.slice(i + 3);
  else if (p.startsWith("p.")) p = p.slice(2);
  else return null;
  const s = p.replace(AA3_RE, (m) => AA3TO1[m] ?? m);
  return s === p ? null : "p." + s;
}

export function spliceaiSourceLabel(src: string | null | undefined): string {
  if (!src) return "";
  if (src === "precomputed") return "precomputed SNV, d=50";
  if (src.startsWith("BroadAPI")) return "Broad lookup (indel), d=500";
  return src;
}
export function neglog10(p: number | null | undefined): number | null {
  if (isNil(p)) return null;
  if (p <= 0) return 320;
  return -Math.log10(p);
}
export function rsids(existing: unknown): string[] {
  return String(existing ?? "").split(/[,&]/).filter((x) => x.startsWith("rs"));
}

/* category colors: pheinfo ships R color names; most are valid CSS */
const FALLBACK_PALETTE = ["#4269d0", "#efb118", "#ff725c", "#6cc5b0", "#3ca951", "#ff8ab7",
  "#a463f2", "#97bbf5", "#9c6b4e", "#9498a0", "#e03131", "#0c8599", "#e8590c", "#5f3dc4",
  "#2b8a3e", "#d6336c", "#1971c2", "#868e96"];
export function catColor(color: string | null | undefined, ord: number | null | undefined): string {
  if (color && CSS.supports("color", color)) return color;
  return FALLBACK_PALETTE[(ord ?? 0) % FALLBACK_PALETTE.length] ?? "#888";
}

/** Render an annotation value according to the field registry's `fmt` hint. */
export function fmtField(f: FieldDef, v: unknown): string {
  if (isNil(v) || v === "") return dash;
  if (f.type === "bool") return v ? "yes" : "no";
  if (f.type === "num" || f.type === "int") {
    const n = Number(v);
    switch (f.fmt) {
      case "p": return fmtP(n);
      case "or": return fmtOR(n);
      case "af": return fmtAF(n);
      case "int": return fmtNum(n);
      case "score1": return fmtScore(n, 1);
      case "score2": return fmtScore(n, 2);
      case "score3": return fmtScore(n, 3);
      default: return Number.isInteger(n) ? fmtNum(n) : fmtScore(n, 3);
    }
  }
  const s = String(v);
  if (f.name === "hgvsc" || f.name === "hgvsp") return `<span class="mono">${esc(hgvsClean(s))}</span>`;
  if (f.name === "consequence") return esc(s.replace(/&/g, ", "));
  if (f.name === "impact" || f.name === "lof") return `<span class="badge ${esc(s)}">${esc(s)}</span>`;
  if (f.name.startsWith("clinvar") || f.name === "clin_sig") return esc(s.replace(/[&|]/g, ", "));
  if (f.name === "existing_variation") return esc(s.replace(/&/g, ", "));
  return esc(s);
}
