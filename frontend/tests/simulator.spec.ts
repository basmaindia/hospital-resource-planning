import { expect, test, type Page } from "@playwright/test";

import { testApiPort } from "../playwright.config";

/** Redirige les appels du dashboard (API 8000) vers l'API de test, qui écrit dans une copie. */
async function useTestApi(page: Page) {
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const response = await route.fetch({ url: route.request().url().replace(":8000", `:${testApiPort}`) });
    await route.fulfill({ response });
  });
}

async function openView(page: Page, name: string) {
  await page.goto("/");
  // Le filtre Scénario est rempli quand les données sont chargées.
  await expect.poll(() => page.locator(".topbar select").nth(1).locator("option").count(), { timeout: 30_000 }).toBeGreaterThanOrEqual(6);
  await page.getByRole("button", { name, exact: true }).click();
}

async function setRange(page: Page, index: number, value: number) {
  await page.locator(".simulator-form input[type=range]").nth(index).fill(String(value));
}

test.beforeEach(async ({ page }) => { await useTestApi(page); });

test("le simulateur lance Naïve et Greedy puis affiche les écarts à S0", async ({ page }) => {
  test.setTimeout(90_000);
  await openView(page, "Simulateur");
  const form = page.locator(".simulator-form");

  // Heuristiques cochées par défaut, solveurs exacts en option avec leur durée.
  const methods = form.locator(".method-check");
  await expect(methods).toHaveCount(4);
  for (const [index, checked] of [true, true, false, false].entries()) {
    expect(await methods.nth(index).locator("input").isChecked()).toBe(checked);
  }
  await expect(methods.nth(2)).toContainText(/≈ \d+ s/);
  await expect(methods.nth(3)).toContainText(/≈ \d+ s/);

  await setRange(page, 0, 130);
  await form.getByLabel("Service concerné").first().selectOption("URG");
  await setRange(page, 1, 15);
  await setRange(page, 2, 10);
  await form.getByLabel("Service concerné").nth(1).selectOption("CHI");

  const submitted = page.waitForRequest((request) => request.method() === "POST");
  await form.getByRole("button", { name: /Lancer la simulation/ }).click();
  expect((await submitted).postDataJSON()).toEqual({
    custom_scenario: { demand_multiplier: 1.3, demand_service: "URG", absence_rate: 0.15, closure_rate: 0.1, closure_service: "CHI" },
    methods: ["naive", "greedy"],
    profile_id: "equilibre",
  });
  await expect(form.getByText(/Simulation terminée en \d+ s/)).toBeVisible({ timeout: 60_000 });

  // Résultat affiché à côté de S0, avec quatre écarts chiffrés par méthode.
  await expect(page.getByRole("heading", { name: "Demande URG ×1,30 · absences 15 % · lits fermés CHI 10 %" })).toBeVisible();
  const results = page.locator(".sim-method");
  await expect(results).toHaveCount(2);
  for (const [index, name] of ["Naïve", "Greedy"].entries()) {
    const card = results.nth(index);
    await expect(card).toContainText(name);
    await expect(card).toContainText("contraintes respectées");
    const rows = card.locator("tbody tr");
    await expect(rows).toHaveCount(4);
    await expect(rows.nth(0)).toContainText("Admissions refusées");
    // Plus de demande et moins de lits : davantage de refus qu'en S0.
    await expect(rows.nth(0).locator(".gap")).toHaveText(/▲ \+\d+.*moins bien/);
    await expect(rows.nth(1).locator(".gap")).toHaveText(/▼ −[\d,]+ pt.*moins bien/);
  }

  // La simulation est retrouvée dans la Comparaison, à part des scénarios S0–S5.
  await page.getByRole("button", { name: "Comparaison scénarios", exact: true }).click();
  await expect(page.locator(".custom-card")).toContainText("Demande URG ×1,30 · absences 15 % · lits fermés CHI 10 %");
  await expect(page.locator(".kpi").first()).toContainText("6");
  await expect(page.locator(".grouped-chart rect")).toHaveCount(24);
});

test("le simulateur signale une fermeture de lits irréalisable", async ({ page }) => {
  test.setTimeout(90_000);
  await openView(page, "Simulateur");
  const form = page.locator(".simulator-form");
  await setRange(page, 0, 100);
  await setRange(page, 1, 0);
  await setRange(page, 2, 40);
  await form.getByLabel("Service concerné").nth(1).selectOption("MED");

  await expect(form.locator(".sim-warning")).toContainText("aucun plan ne peut respecter les contraintes");
  await form.getByRole("button", { name: /Lancer la simulation/ }).click();
  await expect(form.getByText(/Simulation terminée/)).toBeVisible({ timeout: 60_000 });

  await expect(page.locator(".sim-method").first()).toContainText("contraintes non respectées");
  // Un plan irréalisable n'est jamais présenté comme meilleur que S0.
  await expect(page.locator(".sim-method .gap").first()).toHaveText("non comparable");
  await expect(page.locator(".gap-better")).toHaveCount(0);
});

test("la comparaison affiche quatre méthodes par scénario et change de profil", async ({ page }) => {
  await openView(page, "Comparaison scénarios");
  await expect(page.getByRole("heading", { name: "Comparaison des scénarios", exact: true })).toBeVisible();
  const table = page.locator("section.card", { has: page.getByRole("heading", { name: "Tableau comparatif" }) });
  await expect(table.locator("tbody tr")).toHaveCount(24);
  await expect(page.locator(".grouped-chart rect")).toHaveCount(24);
  await expect(page.locator(".kpi").nth(3)).toContainText("Contraintes respectées");
  const objective = await table.locator("tbody tr").first().locator("td").nth(2).innerText();

  const profile = page.getByLabel("Profil de pondération");
  await expect(profile.locator("option")).toHaveText(["Équilibré", "Priorité accueil", "Priorité personnel"]);
  await profile.selectOption("priorite_accueil");
  await expect(page.locator(".profile-card")).toContainText(/refus 5\s000 \(URG ×3\)/);
  await expect(table.locator("tbody tr")).toHaveCount(24);
  await expect(table.locator("tbody tr").first().locator("td").nth(2)).not.toHaveText(objective);
  await expect(page.locator(".best-row").first()).toContainText("ex æquo");

  await page.getByLabel("Indicateur comparé").selectOption("staff_coverage_rate");
  await expect(page.getByRole("heading", { name: /Postes cibles couverts \(%\) — plus haut = meilleur/ })).toBeVisible();
});
