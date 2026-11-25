// Captures du rapport : dashboard (DASHBOARD_URL), Swagger (API_URL/docs) et schémas HTML.
// Utilise le Playwright du dossier frontend ; à lancer contre une API qui écrit dans une COPIE
// des résultats (HOSPITAL_RESULTS_PATH), car la capture du simulateur lance un calcul.
//   DASHBOARD_URL=http://127.0.0.1:3000 API_URL=http://127.0.0.1:8010 node rapport/scripts/captures.cjs
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const root = path.resolve(__dirname, "../..");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? path.join(root, "frontend/node_modules/@playwright/test"));
const dashboard = process.env.DASHBOARD_URL ?? "http://127.0.0.1:3000";
const api = process.env.API_URL ?? "http://127.0.0.1:8010";
const figure = (name) => path.join(root, "rapport/figures", `${name}.png`);

async function clip(page, name, first, last) {
  const a = await first.boundingBox();
  const b = await last.boundingBox();
  const margin = 12;
  await page.screenshot({ path: figure(name), fullPage: true, clip: { x: Math.min(a.x, b.x) - margin, y: a.y - margin, width: Math.max(a.x + a.width, b.x + b.width) - Math.min(a.x, b.x) + 2 * margin, height: b.y + b.height - a.y + 2 * margin } });
}

(async () => {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL ?? (process.platform === "win32" ? "msedge" : undefined) });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: 1.5 });
  const view = async (name) => { await page.getByRole("button", { name, exact: true }).click(); await page.waitForTimeout(1800); await page.evaluate(() => scrollTo(0, 0)); };
  const card = (title) => page.locator("section.card", { has: page.getByRole("heading", { name: title }) }).first();

  await page.goto(dashboard);
  await page.locator(".kpi").first().waitFor({ timeout: 40_000 });
  await page.screenshot({ path: figure("dashboard_overview") });

  await view("Comparaison scénarios");
  await page.setViewportSize({ width: 1400, height: 1180 });
  await page.getByLabel("Indicateur comparé").selectOption("staff_shortage_total");
  await page.waitForTimeout(600);
  await page.screenshot({ path: figure("comparaison_scenarios") });

  await view("Allocation");
  await page.getByLabel("Résultat").selectOption("cp_sat");
  await page.waitForTimeout(1500);
  await clip(page, "allocation_heatmap", page.locator(".kpi").first(), card(/Postes manquants/));
  await clip(page, "allocation_planning", card(/Planning du personnel/), card(/Planning du personnel/));

  await view("Simulateur");
  await page.setViewportSize({ width: 1400, height: 1000 });
  const form = page.locator(".simulator-form");
  await form.locator("input[type=range]").nth(0).fill("130");
  await form.getByLabel("Service concerné").first().selectOption("URG");
  await form.locator("input[type=range]").nth(1).fill("15");
  await form.locator("input[type=range]").nth(2).fill("10");
  await form.getByLabel("Service concerné").nth(1).selectOption("CHI");
  await form.getByRole("button", { name: /Lancer la simulation/ }).click();
  await form.getByText(/Simulation terminée/).waitFor({ timeout: 90_000 });
  await page.waitForTimeout(1500);
  await page.mouse.move(0, 0);
  await page.screenshot({ path: figure("simulateur") });

  await view("Sensibilité");
  await page.mouse.move(0, 0);
  await clip(page, "sensibilite", page.locator(".sensitivity-filters"), page.locator("section.card", { has: page.locator(".heatmap") }));

  await page.setViewportSize({ width: 1400, height: 1000 });
  await page.goto(`${api}/docs`);
  // Swagger charge son interface depuis un CDN : un second essai si le premier chargement est lent.
  try { await page.locator(".opblock").first().waitFor({ timeout: 30_000 }); } catch { await page.reload(); await page.locator(".opblock").first().waitFor({ timeout: 60_000 }); }
  await page.waitForTimeout(800);
  await page.screenshot({ path: figure("swagger_ui") });

  for (const name of ["architecture_pipeline", "obs", "wbs", "gantt"]) {
    await page.goto(pathToFileURL(path.join(root, "rapport/diagrams_source", `${name}.html`)).href);
    await page.locator("#schema").screenshot({ path: figure(name) });
  }
  await browser.close();
})();
