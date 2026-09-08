/* Dataset home: stats + gene index. */
import { esc, fmtNum } from "../format";
import { href } from "../router";
import { datasetEntry, loadMeta } from "../state";

export async function renderHome($app: HTMLElement, ds: string): Promise<void> {
  const meta = await loadMeta(ds);
  const entry = datasetEntry(ds);
  const { genes, stats } = meta;
  const byLetter = new Map<string, typeof genes>();
  genes.slice().sort((a, b) => a.gene.localeCompare(b.gene)).forEach((g) => {
    const L = (g.gene[0] ?? "?").toUpperCase();
    if (!byLetter.has(L)) byLetter.set(L, []);
    byLetter.get(L)!.push(g);
  });
  const cohorts = meta.cohorts.map((c) => c.is_meta ? `<b>${esc(c.label)}</b>` : esc(c.label)).join(" · ");
  $app.innerHTML = `
    <h1>${esc(entry?.name ?? meta.manifest?.name ?? "Dataset")}</h1>
    <div class="subtitle">Variant-level PheWAS · cohorts: ${cohorts}
      ${meta.manifest?.build ? ` · ${esc(meta.manifest.build)}` : ""}
      · ${esc(meta.manifest?.dictionary.label ?? "")}.
      Click a gene to browse its variants, or use the search box above.
      <a href="${href.info(ds)}">Dataset details</a></div>
    <div class="cards">
      <div class="stat-card"><div class="num">${fmtNum(stats.n_genes)}</div><div class="lbl">genes</div></div>
      <div class="stat-card"><div class="num">${fmtNum(stats.n_variants)}</div><div class="lbl">variants</div></div>
      <div class="stat-card"><div class="num">${fmtNum(stats.n_traits)}</div><div class="lbl">phenotypes</div></div>
      <div class="stat-card"><div class="num">${fmtNum(stats.n_assoc)}</div><div class="lbl">associations</div></div>
    </div>
    ${[...byLetter.entries()].map(([L, gs]) => `
      <div class="gene-letter">${esc(L)}</div>
      <div class="gene-chips">
        ${gs.map((g) => `<a class="gene-chip" href="${href.gene(ds, g.gene)}">${esc(g.gene)}
           <small>chr${esc(g.chrom ?? "?")} · ${fmtNum(g.n_variants)} variants</small></a>`).join("")}
      </div>`).join("")}`;
}
