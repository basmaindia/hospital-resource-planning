import os from "node:os";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

const projectRoot = path.resolve(__dirname, "..");
const isWindows = process.platform === "win32";
const python = path.join(projectRoot, ".venv", isWindows ? "Scripts/python.exe" : "bin/python");

/** API de test : vraies méthodes, mais écriture dans une copie temporaire des résultats. */
export const testApiPort = 8012;
export const testResultsPath = path.join(os.tmpdir(), "hospital-planning-e2e-results");

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  reporter: "list",
  globalSetup: "./tests/global-setup.ts",
  use: {
    baseURL: "http://127.0.0.1:3011",
    trace: "retain-on-failure",
    // Edge est présent sur Windows : aucun navigateur à télécharger. Sinon, Chromium de Playwright.
    channel: process.env.PLAYWRIGHT_CHANNEL ?? (isWindows ? "msedge" : undefined),
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: isWindows ? "npm.cmd run dev" : "npm run dev",
      url: "http://127.0.0.1:3011",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: `"${python}" -m uvicorn hospital_planning.api.app:app --host 127.0.0.1 --port ${testApiPort} --log-level warning`,
      cwd: projectRoot,
      env: { PYTHONPATH: "src", PYTHONDONTWRITEBYTECODE: "1", HOSPITAL_PROJECT_ROOT: projectRoot, HOSPITAL_RESULTS_PATH: testResultsPath },
      url: `http://127.0.0.1:${testApiPort}/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
