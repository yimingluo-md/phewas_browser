/* PheWAS Manhattan plot for one variant on one cohort (Plotly). */
import type Plotly from "plotly.js-dist-min";
import { catColor, neglog10 } from "../format";
import type { Association } from "../types";

export async function drawManhattan(element: HTMLElement, assoc: Association[], cohort: string, bonf: number | null): Promise<void> {
  const Plotly = (await import("plotly.js-dist-min")).default; // 4.8 MB, loaded on first variant page only
  if (!element.isConnected) return;
  const sorted = assoc.slice().sort((a, b) =>
    ((a.category_ord ?? 999) - (b.category_ord ?? 999)) || (parseFloat(a.trait) - parseFloat(b.trait)));
  const x = new Map<Association, number>();
  sorted.forEach((a, i) => x.set(a, i));

  const byCat = new Map<string, Association[]>();
  sorted.forEach((a) => {
    const k = a.category ?? "other";
    if (!byCat.has(k)) byCat.set(k, []);
    byCat.get(k)!.push(a);
  });
  const st = (a: Association) => a.cohorts[cohort] ?? {};
  const fmtOr = (v: number | null | undefined) => v === null || v === undefined ? "–" : v >= 100 ? v.toFixed(0) : v.toFixed(2);

  const traces: Plotly.Data[] = [...byCat.entries()].map(([cat, pts]) => ({
    name: cat,
    type: "scatter",
    mode: "markers",
    x: pts.map((a) => x.get(a) ?? 0),
    y: pts.map((a) => neglog10(st(a).p)),
    marker: {
      color: catColor(pts[0]?.color, pts[0]?.category_ord),
      size: 7,
      symbol: pts.map((a) => { const o = st(a).or; return o !== null && o !== undefined && o > 1 ? "triangle-up" : "triangle-down"; }),
      opacity: 0.85,
    },
    text: pts.map((a) => {
      const s = st(a);
      return `<b>${a.trait} — ${a.description ?? ""}</b><br>` +
        `aOR = ${fmtOr(s.or)}, P = ${s.p === null || s.p === undefined ? "–" : s.p.toExponential(2)}<br>` +
        `cases ${s.cases?.toLocaleString() ?? "–"} (carriers ${s.case_carriers ?? "–"}), ` +
        `controls ${s.controls?.toLocaleString() ?? "–"} (carriers ${s.ctrl_carriers ?? "–"})<br>` +
        `cohorts: ${Object.keys(a.cohorts).join(" + ")}`;
    }),
    hoverinfo: "text",
  }));

  const catTicks = [...byCat.entries()].map(([cat, pts]) => ({
    cat, mid: ((x.get(pts[0]!) ?? 0) + (x.get(pts[pts.length - 1]!) ?? 0)) / 2,
  }));
  const shapes: Partial<Plotly.Shape>[] = bonf ? [{
    type: "line", x0: 0, x1: sorted.length, xref: "x",
    y0: -Math.log10(bonf), y1: -Math.log10(bonf), yref: "y",
    line: { dash: "dash", color: "#b3261e", width: 1 },
  }] : [];

  await Plotly.newPlot(element, traces, {
    margin: { l: 55, r: 10, t: 8, b: 110 },
    xaxis: {
      tickvals: catTicks.map((t) => t.mid),
      ticktext: catTicks.map((t) => t.cat),
      tickangle: 45,
      tickfont: { size: 10 },
      showgrid: false,
      zeroline: false,
      range: [-5, sorted.length + 5],
    },
    yaxis: { title: { text: `−log₁₀(P ${cohort})` }, rangemode: "tozero" },
    showlegend: false,
    shapes,
    hoverlabel: { bgcolor: "#fff", font: { size: 12 } },
    dragmode: "pan",
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
  }, { responsive: true, scrollZoom: true, displaylogo: false });
}
