/* Entry point: token, header, hash router -> pages. */
import "./styles.css";
import { ApiError, api, initToken } from "./api";
import { renderHeader } from "./components/header";
import { esc } from "./format";
import { go, href, parse } from "./router";
import { defaultDataset, loadLibrary, setActive } from "./state";
import { renderGene } from "./pages/gene";
import { renderHome } from "./pages/home";
import { renderImport } from "./pages/import";
import { renderInfo } from "./pages/info";
import { renderLibrary } from "./pages/library";
import { renderVariant } from "./pages/variant";

const $app = document.getElementById("app")!;
let nav = 0;

function showError(e: unknown): void {
  const msg = e instanceof ApiError && e.status === 401
    ? "Not authorised: open the browser from the app (or the URL printed by phewas-server), which carries the access token."
    : (e as Error).message || String(e);
  $app.innerHTML = `<div class="error">${esc(msg)}</div>`;
}

async function route(): Promise<void> {
  const my = ++nav;
  const r = parse(location.hash);
  window.scrollTo(0, 0);
  try {
    await loadLibrary();
    if (r.page === "home" && !r.dataset) {
      const ds = await defaultDataset();
      go(ds ? href.home(ds) : href.library());
      return;
    }
    setActive(r.dataset);
    renderHeader();
    $app.innerHTML = '<div class="loading">Loading…</div>';
    if (my !== nav) return;
    switch (r.page) {
      case "library": await renderLibrary($app); break;
      case "import": await renderImport($app); break;
      case "info": await renderInfo($app, r.dataset!); break;
      case "gene": await renderGene($app, r.dataset!, r.gene!); break;
      case "variant": await renderVariant($app, r.dataset!, r.variant!, r.gene ?? null); break;
      default: await renderHome($app, r.dataset!);
    }
  } catch (e) {
    if (my === nav) showError(e);
  }
}

initToken();
window.addEventListener("hashchange", () => void route());
api.health().then(() => void route(), showError);
