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
let navigation: AbortController | undefined;

function showError(e: unknown): void {
  const msg = e instanceof ApiError && e.status === 401
    ? "Not authorised: open the browser from the app (or the URL printed by phewas-server), which carries the access token."
    : (e as Error).message || String(e);
  $app.innerHTML = `<div class="error">${esc(msg)}</div>`;
}

async function route(): Promise<void> {
  const my = ++nav;
  navigation?.abort();
  navigation = new AbortController();
  const signal = navigation.signal;
  const page = document.createElement("div");
  page.innerHTML = '<div class="loading">Loading…</div>';
  $app.replaceChildren(page);
  window.scrollTo(0, 0);
  try {
    const r = parse(location.hash);
    await loadLibrary();
    if (my !== nav) return;
    if (r.page === "home" && !r.dataset) {
      const ds = await defaultDataset();
      if (my !== nav) return;
      go(ds ? href.home(ds) : href.library());
      return;
    }
    setActive(r.dataset);
    renderHeader();
    switch (r.page) {
      case "library": await renderLibrary(page); break;
      case "import": await renderImport(page, signal); break;
      case "info": await renderInfo(page, r.dataset!); break;
      case "gene": await renderGene(page, r.dataset!, r.gene!); break;
      case "variant": await renderVariant(page, r.dataset!, r.variant!, r.gene ?? null); break;
      default: await renderHome(page, r.dataset!);
    }
  } catch (e) {
    if (my === nav) showError(e);
  }
}

initToken();
window.addEventListener("hashchange", () => void route());
api.health().then(() => void route(), showError);
