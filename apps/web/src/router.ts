/* Hash router.
 *   #/                       -> current dataset's home (or the library when empty)
 *   #/library                library
 *   #/import                 import wizard
 *   #/d/<id>                 dataset home (gene list)
 *   #/d/<id>/gene/<gene>
 *   #/d/<id>/variant/<variant>[/<gene>]
 *   #/d/<id>/info            dataset info (manifest, sources, log)
 */

export interface Route {
  page: "library" | "import" | "home" | "gene" | "variant" | "info";
  dataset: string | null;
  gene?: string;
  variant?: string;
}

export function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").map((p) => decodeURIComponent(p));
  if (parts[0] === "library") return { page: "library", dataset: null };
  if (parts[0] === "import") return { page: "import", dataset: null };
  if (parts[0] === "d" && parts[1]) {
    const dataset = parts[1];
    if (parts[2] === "gene" && parts[3]) return { page: "gene", dataset, gene: parts[3] };
    if (parts[2] === "variant" && parts[3]) return { page: "variant", dataset, variant: parts[3], gene: parts[4] };
    if (parts[2] === "info") return { page: "info", dataset };
    return { page: "home", dataset };
  }
  return { page: "home", dataset: null };
}

const e = encodeURIComponent;
export const href = {
  library: () => "#/library",
  import: () => "#/import",
  home: (ds: string) => `#/d/${e(ds)}`,
  gene: (ds: string, gene: string) => `#/d/${e(ds)}/gene/${e(gene)}`,
  variant: (ds: string, variant: string, gene?: string | null) =>
    `#/d/${e(ds)}/variant/${e(variant)}${gene ? "/" + e(gene) : ""}`,
  info: (ds: string) => `#/d/${e(ds)}/info`,
};

export function go(h: string): void { location.hash = h; }
