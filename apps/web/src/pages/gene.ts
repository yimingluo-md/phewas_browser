/* Gene page: variant table whose columns and filters come from the dataset's field registry. */
import { api } from "../api";
import { dash, esc, fmtField, fmtNum, fmtOR, fmtP, hgvspShort, hgvsClean, rsids } from "../format";
import { href } from "../router";
import { loadMeta } from "../state";
import type { FieldDef, VariantRow } from "../types";
import { bindPager, bindSort, checked, downloadCSV, el, headerCell, pagerHtml, sortRows, type SortState, updatePager, val } from "../components/table";

type Row = VariantRow & { hgvsp_short: string | null; _rsid: string | null };

const SHORT_LABEL: Record<string, string> = {
  existing_variation: "rsID", alphamissense_pred: "AM", clinvar_clnsig: "ClinVar", logofunc_prediction: "LoGoFunc",
  gnomade_af: "gnomADe AF", gnomadg_af: "gnomADg AF", max_af: "MAX AF", cadd_phred: "CADD", revel_score: "REVEL",
  spliceai_max_ds: "SpliceAI", lof: "LOFTEE", promoterai_score: "PromoterAI", consequence: "Consequence",
  impact: "IMPACT", hgvsc: "HGVSc", hgvsp: "HGVSp",
};

export async function renderGene($app: HTMLElement, ds: string, gene: string): Promise<void> {
  const [meta, data] = await Promise.all([loadMeta(ds), api.gene(ds, gene)]);
  const { summary } = data;
  const variants: Row[] = data.variants.map((v) => ({
    ...v, hgvsp_short: hgvspShort(v["hgvsp"] as string | null), _rsid: rsids(v["existing_variation"])[0] ?? null,
  }));
  const fields = meta.fields.filter((f) => !f.structural);
  const tableFields = fields.filter((f) => f.table);
  const textFields = fields.filter((f) => f.filter === "text");
  const inFields = fields.filter((f) => f.filter === "in");
  const eqFields = fields.filter((f) => f.filter === "eq");
  const minFields = fields.filter((f) => f.filter === "min");
  const maxFields = fields.filter((f) => f.filter === "max");
  const distinct = (f: FieldDef, split: boolean) =>
    [...new Set(variants.flatMap((v) => {
      const x = v[f.name];
      return x === null || x === undefined ? [] : split ? String(x).split("&") : [String(x)];
    }))].sort();

  const selectHtml = (f: FieldDef, split: boolean) =>
    `<label>${esc(f.label)}<select id="f-${esc(f.name)}"><option value="">all</option>
      ${distinct(f, split).map((c) => `<option>${esc(c)}</option>`).join("")}</select></label>`;

  $app.innerHTML = `
    <h1>${esc(gene)}</h1>
    <div class="subtitle">chr${esc(summary.chrom ?? "?")}:${fmtNum(summary.min_pos)}–${fmtNum(summary.max_pos)}
      &middot; ${fmtNum(summary.n_variants)} variants &middot;
      top hit: ${summary.top_variant
        ? `<a class="vlink" href="${href.variant(ds, summary.top_variant, gene)}">${esc(summary.top_variant)}</a>
           (${esc(summary.top_trait)} — ${esc(summary.top_trait_desc ?? "")}, P = ${fmtP(summary.min_p)})`
        : dash}</div>
    <div class="panel">
      <div class="filters">
        <label>Search (variant / HGVS / rsID)
          <input type="text" id="f-text" placeholder="e.g. R158Q, Arg158Gln, c.473G, rs…" size="26"></label>
        ${inFields.map((f) => selectHtml(f, true)).join("")}
        ${eqFields.map((f) => selectHtml(f, false)).join("")}
        ${maxFields.map((f) => `<label>${esc(f.label)} &le;<input type="number" id="f-${esc(f.name)}" step="any" placeholder="e.g. 0.001"></label>`).join("")}
        ${minFields.map((f) => `<label>${esc(f.label)} &ge;<input type="number" id="f-${esc(f.name)}" step="any" placeholder="e.g. 20"></label>`).join("")}
        <label>Top P &le;<input type="number" id="f-p" step="any" placeholder="e.g. 1e-5"></label>
        <label class="chk"><input type="checkbox" id="f-carr"> carriers &gt; 0</label>
        <span class="note" id="f-count"></span>
      </div>
      <div class="tablewrap"><table id="var-table"><thead></thead><tbody></tbody></table></div>
      ${pagerHtml("pg", '<button id="csv-btn" style="margin-left:auto">Download filtered CSV</button>')}
    </div>`;

  const state: SortState = { key: "pos", dir: 1, page: 0, per: 100 };
  const numeric = new Set<string>(["pos", "min_p", "top_or", "n_traits", "n_carriers",
    ...fields.filter((f) => f.type === "num" || f.type === "int").map((f) => f.name)]);
  let filtered: Row[] = variants;

  const applyFilters = () => {
    const txt = val("f-text").trim().toLowerCase();
    const pmax = parseFloat(val("f-p"));
    const carr = checked("f-carr");
    const ins = inFields.map((f) => [f.name, val(`f-${f.name}`)] as const).filter(([, v]) => v);
    const eqs = eqFields.map((f) => [f.name, val(`f-${f.name}`)] as const).filter(([, v]) => v);
    const maxs = maxFields.map((f) => [f.name, parseFloat(val(`f-${f.name}`))] as const).filter(([, v]) => !isNaN(v));
    const mins = minFields.map((f) => [f.name, parseFloat(val(`f-${f.name}`))] as const).filter(([, v]) => !isNaN(v));
    filtered = variants.filter((v) => {
      if (txt) {
        const hay = [v.variant_id, v.hgvsp_short ?? "", ...textFields.map((f) => hgvsClean(v[f.name] as string | null) ?? "")]
          .join(" ").toLowerCase();
        if (!hay.includes(txt)) return false;
      }
      for (const [k, x] of ins) if (!String(v[k] ?? "").split("&").includes(x)) return false;
      for (const [k, x] of eqs) if (String(v[k] ?? "") !== x) return false;
      for (const [k, x] of maxs) { const y = v[k] as number | null; if (!(y === null || y === undefined || y <= x)) return false; }
      for (const [k, x] of mins) { const y = v[k] as number | null; if (!(y !== null && y !== undefined && y >= x)) return false; }
      if (!isNaN(pmax) && !(v.min_p !== null && v.min_p <= pmax)) return false;
      if (carr && !((v.n_carriers ?? 0) > 0)) return false;
      return true;
    });
    state.page = 0;
    draw();
  };

  const cell = (f: FieldDef, v: Row): string => {
    if (f.name === "existing_variation") return v._rsid ? esc(v._rsid) : dash;
    if (f.name === "hgvsp") {
      const h = hgvsClean(v["hgvsp"] as string | null);
      return `<span class="mono">${esc(h ?? "")}</span>${v.hgvsp_short ? ` <span class="dim">(${esc(v.hgvsp_short)})</span>` : ""}`;
    }
    return fmtField(f, v[f.name]);
  };
  const cls = (f: FieldDef) => (f.type === "num" || f.type === "int") ? "num" : (f.name.startsWith("clinvar") || f.name === "clin_sig" ? "wrapcell" : "");

  const draw = () => {
    const rows = sortRows(filtered, state.key, state.dir, numeric.has(state.key));
    const start = state.page * state.per;
    const pageRows = rows.slice(start, start + state.per);
    el("var-table").querySelector("thead")!.innerHTML = "<tr>" +
      headerCell("Variant", "variant_id", false, state) +
      headerCell("Pos", "pos", true, state) +
      tableFields.map((f) => headerCell(esc(SHORT_LABEL[f.name] ?? f.label), f.name, numeric.has(f.name), state)).join("") +
      headerCell("Carriers", "n_carriers", true, state) +
      headerCell("Top P", "min_p", true, state) +
      headerCell("Top aOR", "top_or", true, state) +
      headerCell("Top phenotype", "top_trait_desc", false, state) + "</tr>";
    el("var-table").querySelector("tbody")!.innerHTML = pageRows.map((v) => `<tr>
        <td><a class="vlink" href="${href.variant(ds, v.variant_id, gene)}">${esc(v.variant_id)}</a></td>
        <td class="num">${fmtNum(v.pos)}</td>
        ${tableFields.map((f) => `<td class="${cls(f)}">${cell(f, v)}</td>`).join("")}
        <td class="num">${fmtNum(v.n_carriers)}</td>
        <td class="num ${v.min_p !== null && v.min_p < 1e-5 ? "sig" : ""}">${fmtP(v.min_p)}</td>
        <td class="num">${fmtOR(v.top_or)}</td>
        <td class="wrapcell">${v.top_trait ? esc(v.top_trait) + " — " + esc(v.top_trait_desc ?? "") : dash}</td>
      </tr>`).join("");
    updatePager("pg", state, rows.length);
    el("f-count").textContent = `${rows.length.toLocaleString()} of ${variants.length.toLocaleString()} variants`;
  };

  bindSort(el("var-table").querySelector("thead")!, state, numeric, draw);
  ["f-text", "f-p", ...maxFields.map((f) => `f-${f.name}`), ...minFields.map((f) => `f-${f.name}`)]
    .forEach((id) => el(id).addEventListener("input", applyFilters));
  ["f-carr", ...inFields.map((f) => `f-${f.name}`), ...eqFields.map((f) => `f-${f.name}`)]
    .forEach((id) => el(id).addEventListener("change", applyFilters));
  bindPager("pg", state, draw);
  el("csv-btn").onclick = () => {
    const cols = ["variant_id", "chrom", "pos", "ref", "alt", ...tableFields.map((f) => f.name), "hgvsp_short",
      "n_carriers", "n_traits", "min_p", "top_or", "top_trait", "top_trait_desc", "cohorts"];
    downloadCSV(`${gene}_variants.csv`, cols, sortRows(filtered, state.key, state.dir, numeric.has(state.key)));
  };
  draw();
}
