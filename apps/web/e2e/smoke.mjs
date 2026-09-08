import { chromium } from "playwright";
import fs from "node:fs";

/* Browser smoke test against a running phewas-server that serves the built frontend.
 *   PHEWAS_URL   server origin (default http://127.0.0.1:8555)
 *   PHEWAS_TOKEN the server's token
 *   SYN_DIR      directory with the synthetic sumstats.tsv.gz + annotation.tsv (tests/fixtures/make_synthetic.py)
 *   SHOTS        where to write screenshots (default e2e/shots)
 * Exits non-zero on any console error, failed request or failed step. */
const BASE = process.env.PHEWAS_URL ?? "http://127.0.0.1:8555";
const TOKEN = process.env.PHEWAS_TOKEN ?? "e2etoken";
const SYN = process.env.SYN_DIR ?? "/tmp/syn";
const out = process.env.SHOTS ?? new URL("./shots", import.meta.url).pathname;
fs.mkdirSync(out, { recursive: true });
const launchOpts = { args: ["--no-sandbox"] };
const browser = process.env.CHROMIUM
  ? await chromium.launch({ ...launchOpts, executablePath: process.env.CHROMIUM })
  : await chromium.launch(launchOpts);
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
page.on("response", (r) => { if (r.status() >= 400) errors.push(`http ${r.status()} ${r.url()}`); });

const shot = async (name) => { await page.screenshot({ path: `${out}/${name}.png`, fullPage: true }); console.log("shot", name); };
const text = async (sel) => (await page.locator(sel).first().textContent())?.trim();

// 1. token in URL -> home of current dataset
await page.goto(`${BASE}/?token=${TOKEN}`);
await page.waitForSelector(".gene-chip");
console.log("url after token strip:", page.url());
console.log("home h1:", await text("h1"), "| cards:", await page.locator(".stat-card").count());
await shot("01-home");

// 2. gene page
await page.click(".gene-chip >> nth=0");
await page.waitForSelector("#var-table tbody tr");
console.log("gene h1:", await text("h1"), "| rows:", await page.locator("#var-table tbody tr").count(),
  "| header cols:", await page.locator("#var-table thead th").count(), "| filters:", await page.locator(".filters label").count());
await shot("02-gene");
// filter: IMPACT = HIGH
await page.selectOption("#f-impact", "HIGH");
await page.waitForTimeout(200);
console.log("after IMPACT=HIGH:", await text("#f-count"));
await page.selectOption("#f-impact", "");
await page.fill("#f-text", "rs");
await page.waitForTimeout(200);
console.log("after text 'rs':", await text("#f-count"));
await page.fill("#f-text", "");
// sort by Top P
await page.click("#var-table thead th[data-key=min_p]");
await page.waitForTimeout(200);
const firstP = await text("#var-table tbody tr >> nth=0 >> td >> nth=-3");
console.log("sorted by top P, first:", firstP);

// 3. variant page
await page.click("#var-table tbody tr >> nth=0 >> a.vlink");
await page.waitForSelector("#assoc-table tbody tr");
await page.waitForSelector("#manhattan .plotly", { timeout: 20000 });
console.log("variant h1:", await text("h1"), "| cards:", await page.locator(".annot-card").count(),
  "| assoc rows:", await page.locator("#assoc-table tbody tr").count(),
  "| assoc cols:", await page.locator("#assoc-table thead th").count(),
  "| cohort toggles:", await page.locator(".toolbar label.chk input[id^=t-]").count());
await shot("03-variant");
await page.check("#t-AoU");
await page.check("#t-UKBB");
await page.waitForTimeout(200);
console.log("with AoU+UKBB cols:", await page.locator("#assoc-table thead th").count());
await shot("04-variant-all-cohorts");

// 4. search
await page.fill("#search", "GENE");
await page.waitForSelector("#search-results div[data-i]");
console.log("search results:", await page.locator("#search-results div[data-i]").count());
await page.keyboard.press("Enter");
await page.waitForSelector("#var-table tbody tr");
console.log("search -> gene page:", await text("h1"));

// 5. info page
await page.click("a.navlink:has-text('details')");
await page.waitForSelector("pre.log");
console.log("info cards:", await page.locator(".annot-card").count(), "| warnings card:", await page.locator(".annot-card.warn").count());
await shot("05-info");

// 6. library
await page.click("nav a:has-text('Library')");
await page.waitForSelector(".ds-card");
console.log("library cards:", await page.locator(".ds-card").count());
await shot("06-library");

// 7. import wizard: inspect + run + progress + done
await page.click("nav a:has-text('Import')");
await page.waitForSelector("#i-sumstats");
await page.fill("#i-sumstats", `${SYN}/sumstats.tsv.gz`);
await page.waitForSelector("#d-sumstats .pill", { timeout: 10000 });
console.log("detect:", (await text("#d-sumstats .detect-row"))?.slice(0, 120));
await page.fill("#i-annotation", `${SYN}/annotation.tsv`);
await page.waitForSelector("#d-annotation .detect-row", { timeout: 10000 });
console.log("annotation detect:", await text("#d-annotation .detect-row"));
await page.fill("#i-name", "Imported from the wizard");
await page.uncheck("#i-current");
await shot("07-import-form");
// file picker opens and lists
await page.click("#b-annotation");
await page.waitForSelector(".fp-entry");
console.log("picker entries:", await page.locator(".fp-entry").count());
await shot("08-picker");
await page.click("#fp-close");
console.log("start enabled:", await page.locator("#i-start").isEnabled());
await page.click("#i-start");
await page.waitForSelector(".success", { timeout: 60000 });
console.log("import result:", (await text(".success"))?.slice(0, 160));
console.log("steps done:", await page.locator("#steps li.done").count(), "/", await page.locator("#steps li").count());
await shot("09-import-done");
await page.click("a.button.primary:has-text('Open the dataset')");
await page.waitForSelector(".gene-chip");
console.log("opened imported dataset:", await text("h1"));
console.log("dataset switcher options:", await page.locator("#ds-switch option").count());

// 8. library actions: rename via prompt
await page.goto(`${BASE}/#/library`);
await page.waitForSelector(".ds-card");
page.once("dialog", (d) => d.accept("Renamed via UI"));
await page.click(".ds-card:not(.current) button[data-act=rename]");
await page.waitForFunction(() => document.body.innerText.includes("Renamed via UI"));
console.log("renamed ok");
page.once("dialog", (d) => d.accept());
await page.click(".ds-card:not(.current) button[data-act=remove]");
await page.waitForFunction(() => document.querySelectorAll(".ds-card").length === 1);
console.log("removed ok; cards:", await page.locator(".ds-card").count());

// 9. unauthorised
const ctx2 = await browser.newContext();
const p2 = await ctx2.newPage();
await p2.goto(`${BASE}/#/library`);
await p2.waitForSelector(".error");
console.log("no token ->", (await p2.locator(".error").textContent())?.slice(0, 60));

console.log("\nERRORS:", errors.length ? errors : "none");
await browser.close();
process.exit(errors.length ? 1 : 0);
