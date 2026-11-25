# CLAUDE.md — contexte pour Claude Code

## Le projet
Mini-projet 4 du module « Santé digitale et ingénierie des systèmes de santé » (ENSAM Rabat, filière INDIA,
Pr. M. Zemzami) : **outil d'aide à la décision pour la planification des ressources hospitalières** (lits + personnel).
Groupe de 6 étudiants. Données **100 % synthétiques** (aucune donnée patient réelle — exigence du cahier des charges).

Livrables exigés par la prof :
1. Modèle documenté (`docs/mathematical_model.md`, `docs/exact_solvers.md`)
2. Interface de simulation de scénarios (dashboard Next.js + API FastAPI)
3. Comparaison chiffrée de plusieurs stratégies d'allocation (Greedy / MILP-CBC / CP-SAT sur S0–S5)

Conditions générales de validation (toutes les mini-projets) : volets technique, normatif, organisationnel et
réglementaire (loi 09-08), au moins un cas dégradé (saturation, absence, fermeture de lits), évaluation chiffrée,
compte rendu technique, démo où chaque membre peut répondre sur tout le projet.

## Pipeline
```
data/synthetic → forecasting (J+1..J+7) → operational requirements → optimization (greedy | milp | cp_sat)
  → experiments (scénarios S0–S5) → API FastAPI (:8000) → dashboard Next.js (:3011)
```
Code : `src/hospital_planning/` ; tests : `tests/` ; config : `configs/hospital.json`, `configs/scenarios.json`.

## Commandes (Windows PowerShell, depuis la racine)
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install . pytest pytest-cov ruff httpx
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q                      # 39 tests
.\.venv\Scripts\python.exe -m ruff check src tests
# Régénérer la comparaison complète (≈ 6 min : MILP et CP-SAT ont une limite de 30 s chacun)
.\.venv\Scripts\python.exe -m hospital_planning.experiments.runner --methods greedy milp cp_sat
# API
.\.venv\Scripts\python.exe -m uvicorn hospital_planning.api.app:app --reload --host 127.0.0.1 --port 8000
# Dashboard (autre terminal)
cd frontend; npm.cmd install; npm.cmd run dev               # http://localhost:3011
npm.cmd run typecheck; npm.cmd run lint
```
Après une modification Python avec une installation non éditable : `pip install --force-reinstall --no-deps .`

## Règles à respecter
- Lancer `pytest -q`, `ruff check src tests`, `npm run typecheck` et `npm run lint` avant chaque commit.
- Les chemins enregistrés dans les artefacts sont **relatifs et en `/`** (portabilité Windows ↔ Linux/macOS).
  Ne jamais réintroduire `str(path)` absolu dans un JSON d'artefact.
- Le hash d'instance (`_scenario_hash`) force `lineterminator="\n"` : sinon l'ID d'expérience change selon l'OS.
- `save_experiment` **fusionne** les méthodes d'une même instance : relancer une méthode ne supprime pas les autres.
- Le dashboard n'affiche jamais de valeur inventée : un KPI absent → état vide explicite.
- Textes de l'interface et documentation en français.

## Endpoints utiles
`/api/v1/dashboard/scenario-comparison` (KPI de toutes les méthodes × scénarios, utilisé par la vue
« Comparaison scénarios »), `/api/v1/experiments`, `/api/v1/dashboard/experiments/{id}/methods/{method}`,
`POST /api/v1/jobs/experiments` (`{"scenario_ids": [...], "methods": [...]}`). Doc interactive : `/docs`.

## Constat important pour le rapport
Sur toutes les instances, Greedy (0,1 s) atteint quasiment l'objectif des solveurs exacts : MILP/CBC s'arrête à la
limite de 30 s sur la solution Greedy fournie en warm start, CP-SAT gagne ≤ 1 point avec un gap déclaré de 3–8 %.
La pénalité de demande non soutenue (1000) domine l'objectif. À interpréter / approfondir (voir PROGRESS.md).
