/* IEI PheWAS Browser — vanilla JS frontend */
"use strict";

const $app = document.getElementById("app");

/* ---------------------------------------------------------------- utils */
const esc = s => String(s).replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const dash = '<span class="dim">–</span>';

function fmtP(p) {
  if (p === null || p === undefined) return dash;
  if (p === 0) return "&lt;1e-320";
  if (p < 1e-4) return p.toExponential(2).replace("e-", "e-");
  return p.toPrecision(3);
}
function fmtOR(x) {
  if (x === null || x === undefined) return dash;
  if (x >= 100) return x.toFixed(0);
  return x.toFixed(2);
}
function fmtAF(x) {
  if (x === null || x === undefined) return dash;
  if (x === 0) return "0";
  if (x < 1e-3) return x.toExponential(2);
  return x.toPrecision(3);
}
function fmtNum(x) {
  if (x === null || x === undefined) return dash;
  return x.toLocaleString();
}
function fmtScore(x, digits = 2) {
  if (x === null || x === undefined) return dash;
  return Number(x).toFixed(digits);
}
function hgvsClean(s) {
  return s ? s.replace(/%3D/g, "=") : s;
}

/* 3-letter -> 1-letter protein notation: "ENSP…:p.Arg158Gln" -> "p.R158Q" */
const AA3TO1 = { Ala: "A", Arg: "R", Asn: "N", Asp: "D", Cys: "C", Gln: "Q", Glu: "E",
  Gly: "G", His: "H", Ile: "I", Leu: "L", Lys: "K", Met: "M", Phe: "F", Pro: "P",
  Ser: "S", Thr: "T", Trp: "W", Tyr: "Y", Val: "V", Sec: "U", Pyl: "O", Ter: "*", Xaa: "X" };
const AA3_RE = /(Ala|Arg|Asn|Asp|Cys|Gln|Glu|Gly|His|Ile|Leu|Lys|Met|Phe|Pro|Ser|Thr|Trp|Tyr|Val|Sec|Pyl|Ter|Xaa)/g;
function hgvspShort(hgvsp) {
  if (!hgvsp) return null;
  let p = hgvsClean(hgvsp);
  const i = p.indexOf(":p.");
  if (i >= 0) p = p.slice(i + 3);
  else if (p.startsWith("p.")) p = p.slice(2);
  else return null;
  const s = p.replace(AA3_RE, m => AA3TO1[m]);
  return s === p ? null : "p." + s;
}

function spliceaiSourceLabel(src) {
  if (!src) return "";
  if (src === "precomputed") return "precomputed SNV, d=50";
  if (src.startsWith("BroadAPI")) return "Broad lookup (indel), d=500";
  return src;
}
function neglog10(p) {
  if (p === null || p === undefined) return null;
  if (p <= 0) return 320;
  return -Math.log10(p);
}

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

/* category colors: pheinfo ships R color names; most are valid CSS */
const FALLBACK_PALETTE = ["#4269d0","#efb118","#ff725c","#6cc5b0","#3ca951","#ff8ab7",
  "#a463f2","#97bbf5","#9c6b4e","#9498a0","#e03131","#0c8599","#e8590c","#5f3dc4",
  "#2b8a3e","#d6336c","#1971c2","#868e96"];
function catColor(color, groupnum) {
  if (color && CSS.supports("color", color)) return color;
  return FALLBACK_PALETTE[(groupnum || 0) % FALLBACK_PALETTE.length];
}

/* ---------------------------------------------------------------- search */
const $search = document.getElementById("search");
const $sres = document.getElementById("search-results");
let searchTimer = null, searchSel = -1;

$search.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const term = $search.value.trim();
  if (!term) { $sres.classList.add("hidden"); return; }
  searchTimer = setTimeout(async () => {
    try {
      const d = await api("/api/search?term=" + encodeURIComponent(term));
      searchSel = -1;
      if (!d.results.length) {
        $sres.innerHTML = '<div class="dim">No matches</div>';
      } else {
        $sres.innerHTML = d.results.map((r, i) =>
          `<div data-i="${i}" data-type="${r.type}" data-id="${esc(r.id)}" data-gene="${esc(r.gene || "")}">
             <span class="stype">${r.type}</span>${esc(r.label)}</div>`).join("");
      }
      $sres.classList.remove("hidden");
    } catch (e) { /* ignore */ }
  }, 180);
});
$sres.addEventListener("mousedown", e => {
  const div = e.target.closest("div[data-type]");
  if (!div) return;
  goTo(div.dataset.type, div.dataset.id, div.dataset.gene);
});
$search.addEventListener("keydown", e => {
  const items = [...$sres.querySelectorAll("div[data-type]")];
  if (e.key === "ArrowDown") { searchSel = Math.min(searchSel + 1, items.length - 1); }
  else if (e.key === "ArrowUp") { searchSel = Math.max(searchSel - 1, 0); }
  else if (e.key === "Enter") {
    const div = items[searchSel >= 0 ? searchSel : 0];
    if (div) goTo(div.dataset.type, div.dataset.id, div.dataset.gene);
    return;
  } else if (e.key === "Escape") { $sres.classList.add("hidden"); return; }
  else return;
  items.forEach((d, i) => d.classList.toggle("active", i === searchSel));
});
document.addEventListener("click", e => {
  if (!e.target.closest(".searchwrap")) $sres.classList.add("hidden");
});
function goTo(type, id, gene) {
  $sres.classList.add("hidden");
  $search.value = "";
  if (type === "gene") location.hash = "#/gene/" + id;
  else location.hash = "#/variant/" + id + "/" + gene;
}

/* ---------------------------------------------------------------- router */
window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", route);

function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  window.scrollTo(0, 0);
  if (parts[0] === "gene" && parts[1]) renderGene(decodeURIComponent(parts[1]));
  else if (parts[0] === "variant" && parts[1]) {
    renderVariant(decodeURIComponent(parts[1]), parts[2] ? decodeURIComponent(parts[2]) : null);
  }
  else renderHome();
}

function showLoading() { $app.innerHTML = '<div class="loading">Loading…</div>'; }
function showError(e) { $app.innerHTML = `<div class="error">${esc(e.message || e)}</div>`; }

/* ---------------------------------------------------------------- generic table sort */
function sortRows(rows, key, dir, numeric) {
  return rows.slice().sort((a, b) => {
    let x = a[key], y = b[key];
    const xn = x === null || x === undefined, yn = y === null || y === undefined;
    if (xn && yn) return 0;
    if (xn) return 1;
    if (yn) return -1;
    if (numeric) { x = +x; y = +y; return dir * (x - y); }
    return dir * String(x).localeCompare(String(y));
  });
}
function headerCell(label, key, numeric, state, extra = "") {
  const arrow = state.key === key ? `<span class="arrow">${state.dir > 0 ? "▲" : "▼"}</span>` : "";
  return `<th data-key="${key}" data-num="${numeric ? 1 : 0}" class="${numeric ? "num" : ""} ${extra}">${label} ${arrow}</th>`;
}

/* ================================================================ HOME */
let metaCache = null;
async function renderHome() {
  showLoading();
  try {
    if (!metaCache) metaCache = await api("/api/meta");
    const { genes, stats } = metaCache;

    const byLetter = new Map();
    genes.slice().sort((a, b) => a.gene.localeCompare(b.gene)).forEach(g => {
      const L = g.gene[0].toUpperCase();
      if (!byLetter.has(L)) byLetter.set(L, []);
      byLetter.get(L).push(g);
    });

    $app.innerHTML = `
      <h1>IEI variant-level PheWAS</h1>
      <div class="subtitle">Exome-wide association of IEI-gene variants with phecodes,
        meta-analysis of All&nbsp;of&nbsp;Us and UK&nbsp;Biobank.
        Click a gene to browse its variants, or use the search box above.</div>
      <div class="cards">
        <div class="stat-card"><div class="num">${fmtNum(stats.n_genes)}</div><div class="lbl">genes</div></div>
        <div class="stat-card"><div class="num">${fmtNum(stats.n_variants)}</div><div class="lbl">variants</div></div>
        <div class="stat-card"><div class="num">${fmtNum(stats.n_traits)}</div><div class="lbl">phecodes</div></div>
        <div class="stat-card"><div class="num">${fmtNum(stats.n_assoc)}</div><div class="lbl">associations</div></div>
      </div>
      ${[...byLetter.entries()].map(([L, gs]) => `
        <div class="gene-letter">${L}</div>
        <div class="gene-chips">
          ${gs.map(g => `<a class="gene-chip" href="#/gene/${esc(g.gene)}">${esc(g.gene)}
             <small>chr${esc(g.chrom ?? "?")} · ${fmtNum(g.n_variants)} variants</small></a>`).join("")}
        </div>`).join("")}`;
  } catch (e) { showError(e); }
}

/* ================================================================ GENE PAGE */
async function renderGene(gene) {
  showLoading();
  let data;
  try { data = await api("/api/gene/" + encodeURIComponent(gene)); }
  catch (e) { return showError(e); }
  const { summary, variants } = data;
  variants.forEach(v => { v.hgvsp_short = hgvspShort(v.hgvsp); });

  const consequences = [...new Set(variants.flatMap(v => (v.consequence || "").split("&")).filter(Boolean))].sort();

  $app.innerHTML = `
    <h1>${esc(gene)}</h1>
    <div class="subtitle">chr${esc(summary.chrom ?? "?")}:${fmtNum(summary.min_pos)}–${fmtNum(summary.max_pos)}
      &middot; ${fmtNum(summary.n_variants)} variants &middot;
      top hit: <a class="vlink" href="#/variant/${esc(summary.top_variant)}/${esc(gene)}">${esc(summary.top_variant)}</a>
      (${esc(summary.top_trait)} — ${esc(summary.top_trait_desc || "")}, P = ${fmtP(summary.min_p)})</div>
    <div class="panel">
      <div class="filters">
        <label>Search (variant / HGVS / rsID)
          <input type="text" id="f-text" placeholder="e.g. R158Q, Arg158Gln, c.473G, rs…" size="26"></label>
        <label>Consequence
          <select id="f-csq"><option value="">all</option>
            ${consequences.map(c => `<option>${esc(c)}</option>`).join("")}</select></label>
        <label>IMPACT
          <select id="f-impact"><option value="">all</option>
            <option>HIGH</option><option>MODERATE</option><option>LOW</option><option>MODIFIER</option></select></label>
        <label>Max gnomAD AF (MAX_AF) &le;
          <input type="number" id="f-af" step="any" placeholder="e.g. 0.001"></label>
        <label>CADD &ge;
          <input type="number" id="f-cadd" step="any" placeholder="e.g. 20"></label>
        <label>Top P &le;
          <input type="number" id="f-p" step="any" placeholder="e.g. 1e-5"></label>
        <label class="chk"><input type="checkbox" id="f-lof"> LOFTEE HC only</label>
        <label class="chk"><input type="checkbox" id="f-carr"> carriers &gt; 0</label>
        <span class="note" id="f-count"></span>
      </div>
      <table id="var-table"><thead></thead><tbody></tbody></table>
      <div class="pager">
        <button id="pg-prev">&larr; Prev</button>
        <span id="pg-info"></span>
        <button id="pg-next">Next &rarr;</button>
        <button id="csv-btn" style="margin-left:auto">Download filtered CSV</button>
      </div>
    </div>`;

  const state = { key: "pos", dir: 1, page: 0, per: 100 };
  let filtered = variants;

  const applyFilters = () => {
    const txt = document.getElementById("f-text").value.trim().toLowerCase();
    const csq = document.getElementById("f-csq").value;
    const imp = document.getElementById("f-impact").value;
    const af = parseFloat(document.getElementById("f-af").value);
    const cadd = parseFloat(document.getElementById("f-cadd").value);
    const pmax = parseFloat(document.getElementById("f-p").value);
    const lof = document.getElementById("f-lof").checked;
    const carr = document.getElementById("f-carr").checked;
    filtered = variants.filter(v => {
      if (txt) {
        const hay = `${v.name} ${v.hgvsc || ""} ${hgvsClean(v.hgvsp) || ""} ${v.hgvsp_short || ""} ${v.existing_variation || ""} ${v.consequence || ""}`.toLowerCase();
        if (!hay.includes(txt)) return false;
      }
      if (csq && !(v.consequence || "").split("&").includes(csq)) return false;
      if (imp && v.impact !== imp) return false;
      if (!isNaN(af) && !(v.max_af === null || v.max_af <= af)) return false;
      if (!isNaN(cadd) && !(v.cadd_phred !== null && v.cadd_phred >= cadd)) return false;
      if (!isNaN(pmax) && !(v.min_p !== null && v.min_p <= pmax)) return false;
      if (lof && v.lof !== "HC") return false;
      if (carr && !(v.n_carriers > 0)) return false;
      return true;
    });
    state.page = 0;
    draw();
  };

  const NUMCOLS = ["pos", "min_p", "top_or", "n_traits", "n_carriers", "gnomade_af",
    "gnomadg_af", "max_af", "cadd_phred", "revel_score", "spliceai_max_ds", "promoterai_score"];

  const draw = () => {
    const rows = sortRows(filtered, state.key, state.dir, NUMCOLS.includes(state.key));
    const start = state.page * state.per;
    const pageRows = rows.slice(start, start + state.per);
    document.querySelector("#var-table thead").innerHTML = "<tr>" +
      headerCell("Variant", "name", false, state) +
      headerCell("Pos", "pos", true, state) +
      headerCell("Consequence", "consequence", false, state) +
      headerCell("IMPACT", "impact", false, state) +
      headerCell("HGVSc", "hgvsc", false, state) +
      headerCell("HGVSp", "hgvsp", false, state) +
      headerCell("rsID", "existing_variation", false, state) +
      headerCell("gnomADe AF", "gnomade_af", true, state) +
      headerCell("gnomADg AF", "gnomadg_af", true, state) +
      headerCell("MAX AF", "max_af", true, state) +
      headerCell("CADD", "cadd_phred", true, state) +
      headerCell("REVEL", "revel_score", true, state) +
      headerCell("AM", "alphamissense_pred", false, state) +
      headerCell("SpliceAI", "spliceai_max_ds", true, state) +
      headerCell("LOFTEE", "lof", false, state) +
      headerCell("LoGoFunc", "logofunc_prediction", false, state) +
      headerCell("PromoterAI", "promoterai_score", true, state) +
      headerCell("ClinVar", "clinvar_clnsig", false, state) +
      headerCell("Carriers", "n_carriers", true, state) +
      headerCell("Top P", "min_p", true, state) +
      headerCell("Top aOR", "top_or", true, state) +
      headerCell("Top phenotype", "top_trait_desc", false, state) + "</tr>";
    document.querySelector("#var-table tbody").innerHTML = pageRows.map(v => {
      const rsids = (v.existing_variation || "").split(/[,&]/).filter(x => x.startsWith("rs"));
      return `<tr>
        <td><a class="vlink" href="#/variant/${esc(v.name)}/${esc(gene)}">${esc(v.name)}</a></td>
        <td class="num">${fmtNum(v.pos)}</td>
        <td>${esc((v.consequence || "").replace(/&/g, ", "))}</td>
        <td>${v.impact ? `<span class="badge ${esc(v.impact)}">${esc(v.impact)}</span>` : dash}</td>
        <td class="mono">${esc(hgvsClean(v.hgvsc) || "")}</td>
        <td class="mono">${esc(hgvsClean(v.hgvsp) || "")}${v.hgvsp_short ? ` <span class="dim">(${esc(v.hgvsp_short)})</span>` : ""}</td>
        <td>${rsids.length ? esc(rsids[0]) : dash}</td>
        <td class="num">${fmtAF(v.gnomade_af)}</td>
        <td class="num">${fmtAF(v.gnomadg_af)}</td>
        <td class="num">${fmtAF(v.max_af)}</td>
        <td class="num">${fmtScore(v.cadd_phred, 1)}</td>
        <td class="num">${fmtScore(v.revel_score)}</td>
        <td>${esc(v.alphamissense_pred || "") || dash}</td>
        <td class="num">${fmtScore(v.spliceai_max_ds)}</td>
        <td>${v.lof ? `<span class="badge ${esc(v.lof)}">${esc(v.lof)}</span>` : dash}</td>
        <td>${esc(v.logofunc_prediction || "") || dash}</td>
        <td class="num">${fmtScore(v.promoterai_score)}</td>
        <td class="wrapcell">${esc(v.clinvar_clnsig || "") || dash}</td>
        <td class="num">${fmtNum(v.n_carriers)}</td>
        <td class="num ${v.min_p !== null && v.min_p < 1e-5 ? "sig" : ""}">${fmtP(v.min_p)}</td>
        <td class="num">${fmtOR(v.top_or)}</td>
        <td class="wrapcell">${v.top_trait ? esc(v.top_trait) + " — " + esc(v.top_trait_desc || "") : dash}</td>
      </tr>`;
    }).join("");
    const npages = Math.max(1, Math.ceil(rows.length / state.per));
    document.getElementById("pg-info").textContent = `page ${state.page + 1} / ${npages}`;
    document.getElementById("f-count").textContent =
      `${rows.length.toLocaleString()} of ${variants.length.toLocaleString()} variants`;
    document.getElementById("pg-prev").disabled = state.page === 0;
    document.getElementById("pg-next").disabled = state.page >= npages - 1;
  };

  document.querySelector("#var-table thead").addEventListener("click", e => {
    const th = e.target.closest("th[data-key]");
    if (!th) return;
    state.dir = state.key === th.dataset.key ? -state.dir : 1;
    state.key = th.dataset.key;
    draw();
  });
  ["f-text", "f-af", "f-cadd", "f-p"].forEach(id =>
    document.getElementById(id).addEventListener("input", applyFilters));
  ["f-csq", "f-impact", "f-lof", "f-carr"].forEach(id =>
    document.getElementById(id).addEventListener("change", applyFilters));
  document.getElementById("pg-prev").onclick = () => { state.page--; draw(); };
  document.getElementById("pg-next").onclick = () => { state.page++; draw(); };
  document.getElementById("csv-btn").onclick = () => {
    const cols = ["name", "pos", "ref", "alt", "consequence", "impact", "hgvsc", "hgvsp",
      "hgvsp_short", "existing_variation", "gnomade_af", "gnomadg_af", "max_af", "cadd_phred", "revel_score",
      "alphamissense_pred", "spliceai_max_ds", "lof", "logofunc_prediction", "promoterai_score",
      "clinvar_clnsig", "n_carriers", "n_traits", "min_p", "top_or", "top_trait", "top_trait_desc"];
    downloadCSV(`${gene}_variants.csv`, cols, sortRows(filtered, state.key, state.dir, NUMCOLS.includes(state.key)));
  };
  draw();
}

/* ================================================================ VARIANT PAGE */
async function renderVariant(name, gene) {
  showLoading();
  let data;
  try {
    data = await api("/api/variant/" + encodeURIComponent(name) +
      (gene ? "?gene=" + encodeURIComponent(gene) : ""));
  } catch (e) { return showError(e); }
  const ann = data.annotation || {};
  const assoc = data.associations;
  gene = data.gene;

  const rsids = (ann.existing_variation || "").split(/[,&]/).filter(x => x.startsWith("rs"));
  const nTests = assoc.length;
  const bonf = nTests ? 0.05 / nTests : null;

  const otherGenes = data.genes_for_variant.filter(g => g !== gene);
  const geneSwitch = otherGenes.length
    ? `<div class="gene-switch">This variant is also annotated for: ${otherGenes.map(g =>
        `<a class="glink" href="#/variant/${esc(name)}/${esc(g)}">${esc(g)}</a>`).join(" ")}</div>`
    : "";

  const dd = (label, valHtml) => `<dt>${label}</dt><dd>${valHtml}</dd>`;
  const card = (title, pairs) => {
    const body = pairs.filter(p => p !== "").join("");
    return body ? `<div class="annot-card"><h3>${title}</h3><dl>${body}</dl></div>` : "";
  };

  $app.innerHTML = `
    <h1 class="mono" style="font-size:20px">${esc(name)}</h1>
    <div class="subtitle">
      <a class="glink" href="#/gene/${esc(gene)}"><b>${esc(gene)}</b></a>
      ${ann.consequence ? " &middot; " + esc(ann.consequence.replace(/&/g, ", ")) : ""}
      ${ann.impact ? ` &middot; <span class="badge ${esc(ann.impact)}">${esc(ann.impact)}</span>` : ""}
      ${rsids.length ? " &middot; " + rsids.map(esc).join(", ") : ""}
      ${ann.mane_select ? ` &middot; MANE: <span class="mono">${esc(ann.mane_select)}</span>` : (ann.canonical ? " &middot; canonical transcript" : "")}
    </div>
    ${geneSwitch}

    <div class="annot-grid">
      ${card("Variant", [
        dd("HGVSc", `<span class="mono">${esc(hgvsClean(ann.hgvsc) || "–")}</span>`),
        dd("HGVSp", `<span class="mono">${esc(hgvsClean(ann.hgvsp) || "–")}</span>${hgvspShort(ann.hgvsp) ? ` <span class="dim">(${esc(hgvspShort(ann.hgvsp))})</span>` : ""}`),
        ann.exon ? dd("Exon", esc(ann.exon)) : (ann.intron ? dd("Intron", esc(ann.intron)) : ""),
        dd("Transcript", `<span class="mono">${esc(ann.transcript || "–")}</span>`),
        dd("Existing variation", esc((ann.existing_variation || "–").replace(/&/g, ", "))),
      ])}
      ${card("Population frequency", [
        dd("gnomAD exomes AF", fmtAF(ann.gnomade_af)),
        dd("gnomAD genomes AF", fmtAF(ann.gnomadg_af)),
        dd("gnomAD popmax AF", ann.gnomad_popmax_af !== null && ann.gnomad_popmax_af !== undefined
          ? `${fmtAF(ann.gnomad_popmax_af)} <span class="dim">${esc(ann.gnomad_popmax_pop || "")}</span>` : dash),
        dd("MAX_AF (all sources)", `${fmtAF(ann.max_af)} <span class="dim">${esc(ann.max_af_pops || "")}</span>`),
      ])}
      ${card("Deleteriousness", [
        dd("CADD (phred)", fmtScore(ann.cadd_phred, 1)),
        dd("REVEL", fmtScore(ann.revel_score, 3)),
        dd("AlphaMissense", ann.alphamissense_pred
          ? `${esc(ann.alphamissense_pred)} <span class="dim">(${fmtScore(ann.alphamissense_score, 3)})</span>` : dash),
        dd("MetaRNN", ann.metarnn_pred
          ? `${esc(ann.metarnn_pred)} <span class="dim">(${fmtScore(ann.metarnn_score, 3)})</span>` : dash),
        dd("PrimateAI", esc(ann.primateai_pred || "–")),
        dd("SIFT", esc(ann.sift_pred || "–")),
        dd("PolyPhen", esc(ann.polyphen || "–")),
        dd("phyloP (100way)", fmtScore(ann.phylop100way, 2)),
      ])}
      ${card("Splicing & LoF", [
        dd("SpliceAI DS (AG/AL/DG/DL)",
          [ann.spliceai_ds_ag, ann.spliceai_ds_al, ann.spliceai_ds_dg, ann.spliceai_ds_dl]
            .map(x => x === null || x === undefined ? "–" : fmtScore(x)).join(" / ")),
        dd("SpliceAI max DS", `${fmtScore(ann.spliceai_max_ds)} <span class="dim">${esc(spliceaiSourceLabel(ann.spliceai_source))}</span>`),
        dd("LOFTEE", ann.lof ? `<span class="badge ${esc(ann.lof)}">${esc(ann.lof)}</span>` : dash),
        ann.lof_filter ? dd("LoF filter", esc(ann.lof_filter)) : "",
        ann.lof_flags ? dd("LoF flags", esc(ann.lof_flags)) : "",
        ann.lof_info ? dd("LoF info", `<span style="font-size:11px">${esc(ann.lof_info)}</span>`) : "",
        dd("50 bp rule (recomputed)", esc(ann.rule_50bp_recomputed || "–")),
      ])}
      ${card("LoGoFunc & regulatory", [
        dd("LoGoFunc prediction", esc(ann.logofunc_prediction || "–")),
        dd("P(GOF) / P(LOF) / P(neutral)",
          [ann.logofunc_gof, ann.logofunc_lof, ann.logofunc_neutral]
            .map(x => x === null || x === undefined ? "–" : fmtScore(x)).join(" / ")),
        dd("PromoterAI", fmtScore(ann.promoterai_score, 3)),
      ])}
      ${card("ClinVar", [
        dd("Clinical significance", esc((ann.clinvar_clnsig || ann.clin_sig || "–").replace(/[&|]/g, ", "))),
        ann.clinvar_clnsigconf ? dd("Conflicting detail", esc(ann.clinvar_clnsigconf)) : "",
        dd("Review status", esc((ann.clinvar_clnrevstat || "–").replace(/&/g, ", "))),
        dd("Disease", `<span style="font-size:11.5px">${esc((ann.clinvar_clndn || "–").replace(/\|/g, " | "))}</span>`),
      ])}
    </div>

    <div class="panel" style="margin-top:16px">
      <h2 style="margin-top:0">PheWAS — ${fmtNum(nTests)} phecodes
        <span class="note" style="font-weight:400">Bonferroni: P &lt; ${bonf ? bonf.toExponential(1) : "–"}
        (dashed line) &middot; &#9650; aOR &gt; 1, &#9660; aOR &lt; 1</span></h2>
      <div id="manhattan"></div>
    </div>

    <div class="panel">
      <div class="toolbar">
        <h2 style="margin:0">Associations</h2>
        <label class="chk" style="margin-left:14px"><input type="checkbox" id="t-aou"> AoU columns</label>
        <label class="chk"><input type="checkbox" id="t-ukbb"> UKBB columns</label>
        <input type="text" id="a-text" placeholder="filter phenotype…" style="padding:5px 8px;border:1px solid var(--border);border-radius:5px">
        <select id="a-cat"><option value="">all categories</option></select>
        <label class="chk"><input type="checkbox" id="a-sig"> P &lt; 0.05 only</label>
        <span class="note" id="a-count"></span>
        <button id="a-csv" style="margin-left:auto">Download CSV</button>
      </div>
      <table id="assoc-table"><thead></thead><tbody></tbody></table>
      <div class="pager">
        <button id="a-prev">&larr; Prev</button>
        <span id="a-info"></span>
        <button id="a-next">Next &rarr;</button>
      </div>
    </div>`;

  /* -------- category dropdown -------- */
  const cats = [...new Set(assoc.map(a => a.category).filter(Boolean))];
  document.getElementById("a-cat").innerHTML +=
    cats.map(c => `<option>${esc(c)}</option>`).join("");

  /* -------- Manhattan plot -------- */
  drawManhattan(assoc, bonf);

  /* -------- association table -------- */
  const state = { key: "p_meta", dir: 1, page: 0, per: 50 };
  let filtered = assoc;

  const applyFilters = () => {
    const txt = document.getElementById("a-text").value.trim().toLowerCase();
    const cat = document.getElementById("a-cat").value;
    const sig = document.getElementById("a-sig").checked;
    filtered = assoc.filter(a => {
      if (txt && !(`${a.trait} ${a.description || ""}`.toLowerCase().includes(txt))) return false;
      if (cat && a.category !== cat) return false;
      if (sig && !(a.p_meta !== null && a.p_meta < 0.05)) return false;
      return true;
    });
    state.page = 0;
    draw();
  };

  const draw = () => {
    const showAou = document.getElementById("t-aou").checked;
    const showUkbb = document.getElementById("t-ukbb").checked;
    const numeric = !["trait", "description", "category", "source"].includes(state.key);
    const rows = sortRows(filtered, state.key, state.dir, numeric);
    const start = state.page * state.per;
    const pageRows = rows.slice(start, start + state.per);

    let head = "<tr>" +
      headerCell("Phecode", "trait", false, state) +
      headerCell("Phenotype", "description", false, state) +
      headerCell("Category", "category", false, state) +
      headerCell("Source", "source", false, state) +
      headerCell("aOR", "or_meta", true, state) +
      headerCell("P", "p_meta", true, state) +
      headerCell("Cases", "cases_meta", true, state) +
      headerCell("Case carr.", "casecarr_meta", true, state) +
      headerCell("Controls", "controls_meta", true, state) +
      headerCell("Ctrl carr.", "ctrlcarr_meta", true, state);
    if (showAou) head +=
      headerCell("aOR AoU", "or_aou", true, state) +
      headerCell("P AoU", "p_aou", true, state) +
      headerCell("Cases AoU", "cases_aou", true, state) +
      headerCell("Case carr. AoU", "casecarr_aou", true, state) +
      headerCell("Controls AoU", "controls_aou", true, state) +
      headerCell("Ctrl carr. AoU", "ctrlcarr_aou", true, state);
    if (showUkbb) head +=
      headerCell("aOR UKBB", "or_ukbb", true, state) +
      headerCell("P UKBB", "p_ukbb", true, state) +
      headerCell("Cases UKBB", "cases_ukbb", true, state) +
      headerCell("Case carr. UKBB", "casecarr_ukbb", true, state) +
      headerCell("Controls UKBB", "controls_ukbb", true, state) +
      headerCell("Ctrl carr. UKBB", "ctrlcarr_ukbb", true, state);
    head += "</tr>";
    document.querySelector("#assoc-table thead").innerHTML = head;

    document.querySelector("#assoc-table tbody").innerHTML = pageRows.map(a => {
      let tds = `
        <td>${esc(a.trait)}</td>
        <td class="wrapcell">${esc(a.description || "")}</td>
        <td><span class="badge" style="background:${catColor(a.color, a.groupnum)}22;color:${catColor(a.color, a.groupnum)}">${esc(a.category || "")}</span></td>
        <td class="dim">${esc((a.source || "").replace("AoU+UKBB", "Meta"))}</td>
        <td class="num">${fmtOR(a.or_meta)}</td>
        <td class="num ${bonf && a.p_meta !== null && a.p_meta < bonf ? "sig" : ""}">${fmtP(a.p_meta)}</td>
        <td class="num">${fmtNum(a.cases_meta)}</td>
        <td class="num">${fmtNum(a.casecarr_meta)}</td>
        <td class="num">${fmtNum(a.controls_meta)}</td>
        <td class="num">${fmtNum(a.ctrlcarr_meta)}</td>`;
      if (showAou) tds += `
        <td class="num">${fmtOR(a.or_aou)}</td><td class="num">${fmtP(a.p_aou)}</td>
        <td class="num">${fmtNum(a.cases_aou)}</td><td class="num">${fmtNum(a.casecarr_aou)}</td>
        <td class="num">${fmtNum(a.controls_aou)}</td><td class="num">${fmtNum(a.ctrlcarr_aou)}</td>`;
      if (showUkbb) tds += `
        <td class="num">${fmtOR(a.or_ukbb)}</td><td class="num">${fmtP(a.p_ukbb)}</td>
        <td class="num">${fmtNum(a.cases_ukbb)}</td><td class="num">${fmtNum(a.casecarr_ukbb)}</td>
        <td class="num">${fmtNum(a.controls_ukbb)}</td><td class="num">${fmtNum(a.ctrlcarr_ukbb)}</td>`;
      return `<tr>${tds}</tr>`;
    }).join("");

    const npages = Math.max(1, Math.ceil(rows.length / state.per));
    document.getElementById("a-info").textContent = `page ${state.page + 1} / ${npages}`;
    document.getElementById("a-count").textContent =
      `${rows.length.toLocaleString()} of ${assoc.length.toLocaleString()} phenotypes`;
    document.getElementById("a-prev").disabled = state.page === 0;
    document.getElementById("a-next").disabled = state.page >= npages - 1;
  };

  document.querySelector("#assoc-table thead").addEventListener("click", e => {
    const th = e.target.closest("th[data-key]");
    if (!th) return;
    state.dir = state.key === th.dataset.key ? -state.dir : 1;
    state.key = th.dataset.key;
    draw();
  });
  ["t-aou", "t-ukbb", "a-cat", "a-sig"].forEach(id =>
    document.getElementById(id).addEventListener("change", id.startsWith("t-") ? draw : applyFilters));
  document.getElementById("a-text").addEventListener("input", applyFilters);
  document.getElementById("a-prev").onclick = () => { state.page--; draw(); };
  document.getElementById("a-next").onclick = () => { state.page++; draw(); };
  document.getElementById("a-csv").onclick = () => {
    const cols = ["trait", "description", "category", "source",
      "or_meta", "p_meta", "cases_meta", "casecarr_meta", "controls_meta", "ctrlcarr_meta",
      "or_aou", "p_aou", "cases_aou", "casecarr_aou", "controls_aou", "ctrlcarr_aou",
      "or_ukbb", "p_ukbb", "cases_ukbb", "casecarr_ukbb", "controls_ukbb", "ctrlcarr_ukbb"];
    downloadCSV(`${name.replace(/:/g, "_")}_${gene}_phewas.csv`, cols, filtered);
  };
  applyFilters();
}

/* -------- Manhattan -------- */
function drawManhattan(assoc, bonf) {
  const sorted = assoc.slice().sort((a, b) =>
    (a.groupnum - b.groupnum) || (parseFloat(a.trait) - parseFloat(b.trait)));
  sorted.forEach((a, i) => a._x = i);

  const byCat = new Map();
  sorted.forEach(a => {
    const k = a.category || "other";
    if (!byCat.has(k)) byCat.set(k, []);
    byCat.get(k).push(a);
  });

  const traces = [...byCat.entries()].map(([cat, pts]) => ({
    name: cat,
    type: "scatter",
    mode: "markers",
    x: pts.map(a => a._x),
    y: pts.map(a => neglog10(a.p_meta)),
    marker: {
      color: catColor(pts[0].color, pts[0].groupnum),
      size: 7,
      symbol: pts.map(a => (a.or_meta !== null && a.or_meta > 1) ? "triangle-up" : "triangle-down"),
      opacity: 0.85,
    },
    text: pts.map(a =>
      `<b>${a.trait} — ${a.description || ""}</b><br>` +
      `aOR = ${a.or_meta === null ? "–" : a.or_meta >= 100 ? a.or_meta.toFixed(0) : a.or_meta.toFixed(2)}, ` +
      `P = ${a.p_meta === null ? "–" : a.p_meta.toExponential(2)}<br>` +
      `cases ${a.cases_meta?.toLocaleString() ?? "–"} (carriers ${a.casecarr_meta ?? "–"}), ` +
      `controls ${a.controls_meta?.toLocaleString() ?? "–"} (carriers ${a.ctrlcarr_meta ?? "–"})<br>` +
      `source: ${(a.source || "").replace("AoU+UKBB", "Meta")}`),
    hoverinfo: "text",
  }));

  const catTicks = [...byCat.entries()].map(([cat, pts]) => ({
    cat, mid: (pts[0]._x + pts[pts.length - 1]._x) / 2,
  }));

  const shapes = bonf ? [{
    type: "line", x0: 0, x1: sorted.length, xref: "x",
    y0: -Math.log10(bonf), y1: -Math.log10(bonf), yref: "y",
    line: { dash: "dash", color: "#b3261e", width: 1 },
  }] : [];

  Plotly.newPlot("manhattan", traces, {
    margin: { l: 55, r: 10, t: 8, b: 110 },
    xaxis: {
      tickvals: catTicks.map(t => t.mid),
      ticktext: catTicks.map(t => t.cat),
      tickangle: 45,
      tickfont: { size: 10 },
      showgrid: false,
      zeroline: false,
      range: [-5, sorted.length + 5],
    },
    yaxis: { title: "−log₁₀(P meta)", rangemode: "tozero" },
    showlegend: false,
    shapes,
    hoverlabel: { bgcolor: "#fff", font: { size: 12 } },
    dragmode: "pan",
  }, { responsive: true, scrollZoom: true, displaylogo: false });
}

/* -------- CSV download -------- */
function downloadCSV(filename, cols, rows) {
  const escCsv = v => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const lines = [cols.join(",")];
  rows.forEach(r => lines.push(cols.map(c => escCsv(r[c])).join(",")));
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
