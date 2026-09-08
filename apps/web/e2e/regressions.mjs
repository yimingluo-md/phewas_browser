import assert from "node:assert/strict";
import { chromium } from "playwright";

const base = process.env.PHEWAS_URL ?? "http://127.0.0.1:8555";
const token = process.env.PHEWAS_TOKEN ?? "e2etoken";
const launchOpts = { args: ["--no-sandbox"] }; // same as smoke.mjs: containers and CI runners
const browser = await chromium.launch(process.env.CHROMIUM ? { ...launchOpts, executablePath: process.env.CHROMIUM } : launchOpts);
const failures = [];
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const json = (route, body) => route.fulfill({ json: body });

async function test(name, run) {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  try {
    await page.goto(`${base}/?token=${encodeURIComponent(token)}`);
    await page.waitForSelector(".gene-chip");
    await run(page);
    assert.deepEqual(errors, [], "uncaught browser errors");
    console.log("PASS", name);
  } catch (e) {
    failures.push(name);
    console.error("FAIL", name, e.message);
  } finally { await page.close(); }
}

try {
  await test("search results follow the latest query", async (page) => {
    await page.route("**/api/v1/datasets/*/search?*", async (route) => {
      const term = new URL(route.request().url()).searchParams.get("q");
      if (term === "GENEA") await delay(650);
      await json(route, { results: [{ type: "gene", id: term, label: term }] });
    });
    const pending = page.waitForRequest("**/search?q=GENEA");
    await page.fill("#search", "GENEA");
    await pending;
    await page.fill("#search", "GENEB");
    await page.waitForSelector("#search-results div[data-i]");
    await delay(700);
    assert.equal(await page.locator("#search-results div[data-i]").textContent(), "geneGENEB");
  });

  await test("the launch token works when browser storage is unavailable", async (page) => {
    await page.addInitScript(() => {
      Storage.prototype.setItem = () => { throw new DOMException("Storage disabled", "SecurityError"); };
      Storage.prototype.getItem = () => null;
    });
    await page.goto(`${base}/?token=${encodeURIComponent(token)}`);
    await page.waitForSelector(".gene-chip", { timeout: 3000 });
  });

  await test("slow gene response cannot overwrite a newer route", async (page) => {
    let release;
    const blocked = new Promise((resolve) => { release = resolve; });
    await page.route("**/api/v1/datasets/*/genes/*", async (route) => {
      const response = await route.fetch();
      await blocked;
      await route.fulfill({ response });
    });
    const request = page.waitForRequest("**/api/v1/datasets/*/genes/*");
    await page.click(".gene-chip >> nth=0");
    await request;
    await page.click("nav a:has-text('Library')");
    await page.waitForSelector(".ds-card");
    release();
    await delay(300);
    assert.equal(await page.locator("h1").textContent(), "Library");
    assert.equal(await page.locator("#var-table").count(), 0);
  });

  await test("leaving the wizard during inspection is safe", async (page) => {
    await page.route("**/api/v1/import/inspect", async (route) => {
      await delay(350);
      await json(route, { sumstats: { exists: false, problems: ["file not found"] } });
    });
    await page.click("nav a:has-text('Import')");
    await page.waitForSelector("#i-sumstats");
    const pending = page.waitForRequest("**/api/v1/import/inspect");
    await page.fill("#i-sumstats", "/missing.tsv");
    await pending;
    await page.click("nav a:has-text('Library')");
    await page.waitForSelector(".ds-card");
    await delay(450);
  });

  const job = { id: "regression", kind: "import", status: "running", step: "stage", done: 0, total: 1,
    message: "", error: null, result: null, warnings: [], created: 1, started: 1, finished: null, seq: 1,
    request: { sumstats: "/synthetic.tsv", name: "Regression import" } };
  const done = { ...job, seq: 2, status: "done", step: "done", finished: 2,
    result: { dataset_id: "synthetic", name: "Regression import", seconds: 1, stats: {} } };

  await test("a broken progress stream keeps following the running job", async (page) => {
    await page.route("**/api/v1/jobs", (route) => json(route, [job]));
    await page.route("**/api/v1/jobs/regression/events?*", (route) => route.fulfill({
      contentType: "text/event-stream", body: `data: ${JSON.stringify(job)}\n\n`,
    }));
    let polls = 0;
    await page.route("**/api/v1/jobs/regression", (route) => json(route, ++polls < 2 ? job : done));
    await page.click("nav a:has-text('Import')");
    await page.waitForSelector(".success", { timeout: 6000 });
    assert.ok(polls >= 2);
  });

  await test("progress updates do not touch a page that was left", async (page) => {
    await page.route("**/api/v1/jobs", (route) => json(route, [job]));
    await page.route("**/api/v1/jobs/regression/events?*", async (route) => {
      await delay(400);
      await route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify(done)}\n\n` });
    });
    await page.click("nav a:has-text('Import')");
    await page.waitForSelector("#cancel");
    await page.click("nav a:has-text('Library')");
    await page.waitForSelector(".ds-card");
    await delay(550);
    assert.equal(await page.locator("h1").textContent(), "Library");
  });

  await test("cancelled imports can return to the form", async (page) => {
    let visits = 0;
    await page.route("**/api/v1/jobs", (route) => json(route, visits++ ? [] : [job]));
    await page.route("**/api/v1/jobs/regression/events?*", (route) => route.fulfill({
      contentType: "text/event-stream", body: `data: ${JSON.stringify({ ...job, seq: 2, status: "cancelled" })}\n\n`,
    }));
    await page.click("nav a:has-text('Import')");
    await page.getByText("Start again", { exact: true }).click();
    await page.waitForSelector("#i-sumstats", { timeout: 3000 });
  });
} finally { await browser.close(); }
assert.deepEqual(failures, [], "browser regressions");
