/* Variant page: annotation cards (from the field registry), Manhattan plot and the association
 * table with one column group per cohort (from the manifest). */
import { api } from "../api";
import { catColor, dash, esc, fmtField, fmtNum, fmtOR, fmtP, fmtScore, hgvsClean, hgvspShort, rsids, spliceaiSourceLabel } from "../format";
import { href } from "../router";
import { loadMeta } from "../state";
import type { Association, Cohort, FieldDef, Stat } from "../types";
import { bindPager, bindSort, checked, downloadCSV, el, headerCell, pagerHtml, sortRows, type SortState, updatePager, val } from "../components/table";
import { drawManhattan } from "../plots/manhattan";

/** Cohort statistics shown per cohort in the association table, in order. */
const TABLE_STATS: { stat: Stat; label: string; fmt: (v: number | null | undefined) => string }[] = [
  { stat: "or", label: "aOR", fmt: fmtOR },
  { stat: "p", label: "P", fmt: fmtP },
  { stat: "cases", label: "Cases", fmt: fmtNum },
  { stat: "case_carriers", label: "Case carr.", fmt: fmtNum },
  { stat: "controls", label: "Controls", fmt: fmtNum },
  { stat: "ctrl_carriers", label: "Ctrl carr.", fmt: fmtNum },
  { stat: "beta", label: "β", fmt: (v) => fmtScore(v, 3) },
  { stat: "se", label: "SE", fmt: (v) => fmtScore(v, 3) },
];

/** Fields that are rendered together as one row rather than one row each. */
const COMPOSITES: { label: string; group: string; fields: string[]; render: (a: Record<string, unknown>) => string }[] = [
  { label: "SpliceAI DS (AG/AL/DG/DL)", group: "Splicing & LoF",
    fields: ["spliceai_ds_ag", "spliceai_ds_al", "spliceai_ds_dg", "spliceai_ds_dl"],
    render: (a) => ["spliceai_ds_ag", "spliceai_ds_al", "spliceai_ds_dg", "spliceai_ds_dl"]
      .map((k) => a[k] === null || a[k] === undefined ? "–" : fmtScore(a[k] as number)).join(" / ") },
  { label: "SpliceAI max DS", group: "Splicing & LoF", fields: ["spliceai_max_ds", "spliceai_source"],
    render: (a) => `${fmtScore(a["spliceai_max_ds"] as number | null)} <span class="dim">${esc(spliceaiSourceLabel(a["spliceai_source"] as string | null))}</span>` },
  { label: "gnomAD popmax AF", group: "Population frequency", fields: ["gnomad_popmax_af", "gnomad_popmax_pop"],
    render: (a) => a["gnomad_popmax_af"] === null || a["gnomad_popmax_af"] === undefined ? dash
      : `${fmtField({ fmt: "af", type: "num" } as FieldDef, a["gnomad_popmax_af"])} <span class="dim">${esc(a["gnomad_popmax_pop"] ?? "")}</span>` },
  { label: "MAX_AF (all sources)", group: "Population frequency", fields: ["max_af", "max_af_pops"],
    render: (a) => `${fmtField({ fmt: "af", type: "num" } as FieldDef, a["max_af"])} <span class="dim">${esc(a["max_af_pops"] ?? "")}</span>` },
  { label: "P(GOF) / P(LOF) / P(neutral)", group: "LoGoFunc & regulatory",
    fields: ["logofunc_gof", "logofunc_lof", "logofunc_neutral"],
    render: (a) => ["logofunc_gof", "logofunc_lof", "logofunc_neutral"]
      .map((k) => a[k] === null || a[k] === undefined ? "–" : fmtScore(a[k] as number)).join(" / ") },
  { label: "AlphaMissense", group: "Deleteriousness", fields: ["alphamissense_pred", "alphamissense_score"],
    render: (a) => a["alphamissense_pred"] ? `${esc(a["alphamissense_pred"])} <span class="dim">(${fmtScore(a["alphamissense_score"] as number | null, 3)})</span>` : dash },
  { label: "MetaRNN", group: "Deleteriousness", fields: ["metarnn_pred", "metarnn_score"],
    render: (a) => a["metarnn_pred"] ? `${esc(a["metarnn_pred"])} <span class="dim">(${fmtScore(a["metarnn_score"] as number | null, 3)})</span>` : dash },
  { label: "HGVSp", group: "Variant", fields: ["hgvsp"],
    render: (a) => { const h = hgvsClean(a["hgvsp"] as string | null); const s = hgvspShort(a["hgvsp"] as string | null);
      return `<span class="mono">${esc(h ?? "–")}</span>${s ? ` <span class="dim">(${esc(s)})</span>` : ""}`; } },
];
const ALWAYS_SHOW = new Set(["hgvsc", "hgvsp", "transcript", "existing_variation", "gnomade_af", "gnomadg_af",
  "cadd_phred", "revel_score", "clinvar_clnsig", "lof", "logofunc_prediction", "promoterai_score"]);

export async function renderVariant($app: HTMLElement, ds: string, variantId: string, geneArg: string | null): Promise<void> {
  const [meta, data] = await Promise.all([loadMeta(ds), api.variant(ds, variantId, geneArg)]);
  if (!$app.isConnected) return;
  const name = data.variant_id;
  const gene = data.gene;
  const ann = data.annotation ?? {};
  const assoc = data.associations;
  const cohorts: Cohort[] = meta.cohorts;
  const primary = cohorts.find((c) => c.primary) ?? cohorts[0]!;
  const others = cohorts.filter((c) => c.id !== primary.id);
  const CORE = new Set<Stat>(["or", "p", "cases", "case_carriers", "controls", "ctrl_carriers"]);
  const allStats = TABLE_STATS.filter((s) => meta.statistics.includes(s.stat));
  const extraStats = allStats.filter((s) => !CORE.has(s.stat));
  let stats = allStats.filter((s) => CORE.has(s.stat));
  const nTests = assoc.length;
  const bonf = nTests ? 0.05 / nTests : null;
  const ids = rsids(ann["existing_variation"]);

  const otherGenes = data.genes_for_variant.filter((g) => g !== gene);
  const geneSwitch = otherGenes.length
    ? `<div class="gene-switch">This variant is also annotated for: ${otherGenes.map((g) =>
      `<a class="glink" href="${href.variant(ds, name, g)}">${esc(g)}</a>`).join(" ")}</div>`
    : "";

  /* ---- annotation cards: one per field group, rows from the registry ---- */
  const groups = new Map<string, string[]>();
  const consumed = new Set(COMPOSITES.flatMap((c) => c.fields));
  const byName = new Map(meta.fields.map((f) => [f.name, f]));
  const skipInCards = new Set(["variant_id", "gene", "chrom", "pos", "ref", "alt", "consequence", "impact", "mane_select", "canonical"]);
  const push = (g: string, html: string) => { if (!groups.has(g)) groups.set(g, []); groups.get(g)!.push(html); };
  const dd = (label: string, valHtml: string) => `<dt>${esc(label)}</dt><dd>${valHtml}</dd>`;
  const seenComposite = new Set<string>();
  for (const f of meta.fields) {
    if (skipInCards.has(f.name)) continue;
    const comp = COMPOSITES.find((c) => c.fields.includes(f.name));
    if (comp) {
      if (seenComposite.has(comp.label)) continue;
      seenComposite.add(comp.label);
      const anyValue = comp.fields.some((k) => ann[k] !== null && ann[k] !== undefined);
      if (anyValue || ALWAYS_SHOW.has(f.name)) push(comp.group, dd(comp.label, comp.render(ann)));
      continue;
    }
    if (consumed.has(f.name)) continue;
    const v = ann[f.name];
    if ((v === null || v === undefined || v === "") && !ALWAYS_SHOW.has(f.name)) continue;
    push(f.group, dd(f.label, f.name === "lof_info" ? `<span style="font-size:11px">${esc(v)}</span>` : fmtField(f, v)));
  }
  const cards = [...groups.entries()].map(([title, rows]) =>
    `<div class="annot-card"><h3>${esc(title)}</h3><dl>${rows.join("")}</dl></div>`).join("");
  const impactF = byName.get("impact");
  const csq = ann["consequence"] as string | null;

  $app.innerHTML = `
    <h1 class="mono" style="font-size:20px">${esc(name)}</h1>
    <div class="subtitle">
      <a class="glink" href="${href.gene(ds, gene)}"><b>${esc(gene)}</b></a>
      ${csq ? " &middot; " + esc(csq.replace(/&/g, ", ")) : ""}
      ${ann["impact"] && impactF ? ` &middot; ${fmtField(impactF, ann["impact"])}` : ""}
      ${ids.length ? " &middot; " + ids.map(esc).join(", ") : ""}
      ${ann["mane_select"] ? ` &middot; MANE: <span class="mono">${esc(ann["mane_select"])}</span>` : (ann["canonical"] ? " &middot; canonical transcript" : "")}
      ${data.variant?.pos ? ` &middot; chr${esc(data.variant.chrom)}:${fmtNum(data.variant.pos)}` : ""}
    </div>
    ${geneSwitch}
    ${cards ? `<div class="annot-grid">${cards}</div>` : `<div class="note">No annotation was imported for this dataset.</div>`}

    <div class="panel" style="margin-top:16px">
      <h2 style="margin-top:0">PheWAS — ${fmtNum(nTests)} phenotypes
        <span class="note" style="font-weight:400">${esc(primary.label)} · Bonferroni: P &lt; ${bonf ? bonf.toExponential(1) : "–"}
        (dashed line) &middot; &#9650; aOR &gt; 1, &#9660; aOR &lt; 1</span></h2>
      <div id="manhattan"></div>
    </div>

    <div class="panel">
      <div class="toolbar">
        <h2 style="margin:0">Associations</h2>
        ${others.map((c) => `<label class="chk" style="margin-left:14px"><input type="checkbox" id="t-${esc(c.id)}"> ${esc(c.label)} columns</label>`).join("")}
        ${extraStats.length ? `<label class="chk"><input type="checkbox" id="t-extra"> ${extraStats.map((s) => esc(s.label)).join(", ")}</label>` : ""}
        <input type="text" id="a-text" placeholder="filter phenotype…" class="inline-input">
        <select id="a-cat"><option value="">all categories</option></select>
        <label class="chk"><input type="checkbox" id="a-sig"> P &lt; 0.05 only</label>
        <span class="note" id="a-count"></span>
        <button id="a-csv" style="margin-left:auto">Download CSV</button>
      </div>
      <div class="tablewrap"><table id="assoc-table"><thead></thead><tbody></tbody></table></div>
      ${pagerHtml("a")}
    </div>`;

  const cats = [...new Set(assoc.map((a) => a.category).filter((c): c is string => !!c))];
  el("a-cat").innerHTML += cats.map((c) => `<option>${esc(c)}</option>`).join("");

  const plot = el("manhattan");
  void drawManhattan(plot, assoc, primary.id, bonf).catch((e) => {
    if (plot.isConnected) plot.textContent = `Plot could not load: ${(e as Error).message}`;
  });

  /* ---- association table ---- */
  type Flat = Record<string, unknown> & { _a: Association };
  const key = (c: string, s: Stat) => `${s}__${c}`;
  const flat: Flat[] = assoc.map((a) => {
    const row: Flat = { _a: a, trait: a.trait, description: a.description, category: a.category,
      source: Object.keys(a.cohorts).filter((c) => c !== primary.id || cohorts.length === 1).join("+") };
    for (const c of cohorts) for (const s of allStats) row[key(c.id, s.stat)] = a.cohorts[c.id]?.[s.stat] ?? null;
    return row;
  });
  const state: SortState = { key: key(primary.id, "p"), dir: 1, page: 0, per: 50 };
  const numeric = new Set(cohorts.flatMap((c) => allStats.map((s) => key(c.id, s.stat))));
  let filtered = flat;

  const applyFilters = () => {
    const txt = val("a-text").trim().toLowerCase();
    const cat = val("a-cat");
    const sig = checked("a-sig");
    filtered = flat.filter((r) => {
      const a = r._a;
      if (txt && !(`${a.trait} ${a.description ?? ""}`.toLowerCase().includes(txt))) return false;
      if (cat && a.category !== cat) return false;
      const p = a.cohorts[primary.id]?.p;
      if (sig && !(p !== null && p !== undefined && p < 0.05)) return false;
      return true;
    });
    state.page = 0;
    draw();
  };

  const draw = () => {
    const shown = [primary, ...others.filter((c) => checked(`t-${c.id}`))];
    stats = extraStats.length && checked("t-extra") ? allStats : allStats.filter((s) => CORE.has(s.stat));
    const rows = sortRows(filtered, state.key, state.dir, numeric.has(state.key));
    const start = state.page * state.per;
    const pageRows = rows.slice(start, start + state.per);
    const suffix = (c: Cohort) => c.id === primary.id ? "" : ` ${c.id}`;
    el("assoc-table").querySelector("thead")!.innerHTML = "<tr>" +
      headerCell("Phecode", "trait", false, state) +
      headerCell("Phenotype", "description", false, state) +
      headerCell("Category", "category", false, state) +
      headerCell("Cohorts", "source", false, state) +
      shown.map((c) => stats.map((s) => headerCell(esc(s.label + suffix(c)), key(c.id, s.stat), true, state, c.id === primary.id ? "" : "alt")).join("")).join("") +
      "</tr>";
    el("assoc-table").querySelector("tbody")!.innerHTML = pageRows.map((r) => {
      const a = r._a;
      const p = a.cohorts[primary.id]?.p;
      const color = catColor(a.color, a.category_ord);
      return `<tr>
        <td>${esc(a.trait)}</td>
        <td class="wrapcell">${esc(a.description ?? "")}</td>
        <td><span class="badge" style="background:${color}22;color:${color}">${esc(a.category ?? "")}</span></td>
        <td class="dim">${esc(r["source"])}</td>
        ${shown.map((c) => stats.map((s) => {
          const v = a.cohorts[c.id]?.[s.stat];
          const sig = s.stat === "p" && c.id === primary.id && bonf && p !== null && p !== undefined && p < bonf ? "sig" : "";
          return `<td class="num ${sig}">${s.fmt(v)}</td>`;
        }).join("")).join("")}
      </tr>`;
    }).join("");
    updatePager("a", state, rows.length);
    el("a-count").textContent = `${rows.length.toLocaleString()} of ${assoc.length.toLocaleString()} phenotypes`;
  };

  bindSort(el("assoc-table").querySelector("thead")!, state, numeric, draw);
  others.forEach((c) => el(`t-${c.id}`).addEventListener("change", draw));
  if (extraStats.length) el("t-extra").addEventListener("change", draw);
  ["a-cat", "a-sig"].forEach((id) => el(id).addEventListener("change", applyFilters));
  el("a-text").addEventListener("input", applyFilters);
  bindPager("a", state, draw);
  el("a-csv").onclick = () => {
    const cols = ["trait", "description", "category", "source", ...cohorts.flatMap((c) => allStats.map((s) => key(c.id, s.stat)))];
    const headers = ["trait", "description", "category", "cohorts", ...cohorts.flatMap((c) => allStats.map((s) => `${s.stat}_${c.id}`))];
    downloadCSV(`${name.replace(/:/g, "_")}_${gene}_phewas.csv`, cols, filtered, headers);
  };
  applyFilters();
}
