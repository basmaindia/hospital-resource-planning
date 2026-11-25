# Sources des schémas et des captures

Les images du rapport sont dans `rapport/figures/`. Le rapport les inclut avec la macro `\captureimg{<nom>}`.

| Source | Image | Contenu |
|---|---|---|
| `architecture_pipeline.html` | `architecture_pipeline.png` | Chaîne de traitement (chapitre 4) |
| `obs.html` | `obs.png` | Répartition de l'équipe (chapitre 1) |
| `wbs.html` | `wbs.png` | Lots de travail (chapitre 1) |
| `gantt.html` | `gantt.png` | Planning prévisionnel (chapitre 1) |

`style.css` est commun aux quatre schémas. Les vues du tableau de bord (`dashboard_overview`, `comparaison_scenarios`, `allocation_heatmap`, `allocation_planning`, `simulateur`, `sensibilite`) et `swagger_ui` sont des captures réelles.

## Régénérer

Démarrer l'API et le tableau de bord, de préférence sur une copie de `results/` (variable `HOSPITAL_RESULTS_PATH`), puis lancer `rapport/scripts/captures.cjs` avec Node et Playwright. Les adresses se règlent avec `DASHBOARD_URL` et `API_URL`.

Les tableaux et les chiffres sont produits par `rapport/scripts/generate_tables.py` (`PYTHONPATH=src`), qui écrit dans `rapport/tables/`. Ne pas modifier ces fichiers à la main.
