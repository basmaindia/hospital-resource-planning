import fs from "node:fs";
import path from "node:path";

import { testResultsPath } from "../playwright.config";

/** Copie les résultats publiés, sans les simulations locales : les tests n'écrivent jamais dans le projet. */
export default function globalSetup() {
  const source = path.resolve(__dirname, "../../results/experiments");
  fs.rmSync(testResultsPath, { recursive: true, force: true });
  fs.cpSync(source, testResultsPath, { recursive: true, filter: (item) => !path.basename(item).startsWith("experiment-custom_") });
}
