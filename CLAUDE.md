# CLAUDE.md — contexte pour Claude Code

## Le projet
Mini-projet 4 du module « Santé digitale et ingénierie des systèmes de santé » (ENSAM Rabat, filière INDIA,
Pr. M. Zemzami) : **outil d'aide à la décision pour la planification des ressources hospitalières** (lits + personnel).
Groupe de 6 étudiants. Données **100 % synthétiques** (aucune donnée patient réelle — exigence du cahier des charges).

Livrables exigés par la prof :
1. Modèle documenté (`docs/mathematical_model.md`, `docs/exact_solvers.md`)
2. Interface de simulation de scénarios (dashboard Next.js + API FastAPI)
3. Comparaison chiffrée de plusieurs stratégies d'allocation (Naïve / Greedy / MILP-CBC / CP-SAT sur S0–S5, 3 profils de pondération)

Conditions générales de validation (toutes les mini-projets) : volets technique, normatif, organisationnel et
réglementaire (loi 09-08), au moins un cas dégradé (saturation, absence, fermeture de lits), évaluation chiffrée,
compte rendu technique, démo où chaque membre peut répondre sur tout le projet.

## Pipeline
```
data/synthetic → forecasting (J+1..J+7) → operational requirements → optimization (naive | greedy | milp | cp_sat)
  → experiments (scénarios S0–S5) → API FastAPI (:8000) → dashboard Next.js (:3011)
```
Code : `src/hospital_planning/` ; tests : `tests/` ; config : `configs/hospital.json`, `configs/scenarios.json`.

## Commandes (Windows PowerShell, depuis la racine)
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install . pytest pytest-cov ruff httpx
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q                      # 78 tests
.\.venv\Scripts\python.exe -m ruff check src tests
# Régénérer la comparaison complète (≈ 32 min, PC branché et sans veille : 50 s et 8 threads par solveur exact)
.\.venv\Scripts\python.exe -m hospital_planning.experiments.runner --methods naive greedy milp cp_sat --profiles equilibre priorite_accueil priorite_personnel
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
  Ne jamais réintroduire `str(path)` absolu dans un JSON d'artefact (`method_result.json` : relatif à son dossier).
- Budget des solveurs : `solver_time_limit_seconds` et `solver_num_workers` dans `configs/hospital.json`, ≤ 2 min par scénario.
- `demand_config_hash` exclut solveurs, politique et poids : les modifier ne périme ni les prévisions ni l'instance S0.
- `scenario-comparison` retient le profil `equilibre` et la graine de référence (`random_seed`) ; `?profile=` et `?seed=` pour d'autres.
  Ne jamais mélanger les objectifs de deux profils ; une expérience par profil (suffixe de l'identifiant).
- Équité : agents présents au moins une fois sur l'horizon seulement (métrique, validateur, MILP et CP-SAT alignés).
- Le hash d'instance (`_scenario_hash`) force `lineterminator="\n"` : sinon l'ID d'expérience change selon l'OS.
- `save_experiment` **fusionne** les méthodes d'une même instance : relancer une méthode ne supprime pas les autres.
- Le dashboard n'affiche jamais de valeur inventée : un KPI absent → état vide explicite.
- Textes de l'interface et documentation en français.

## Endpoints utiles
`/api/v1/dashboard/scenario-comparison` (KPI de toutes les méthodes × scénarios, utilisé par la vue
« Comparaison scénarios »), `/api/v1/experiments`, `/api/v1/dashboard/experiments/{id}/methods/{method}`,
`POST /api/v1/jobs/experiments` (`{"scenario_ids": [...], "methods": [...]}`). Doc interactive : `/docs`.

## Constat important pour le rapport
72 résultats (6 scénarios × 3 profils × 4 méthodes), tous valides ; seul S3 « priorité accueil » est prouvé optimal.
- CP-SAT est meilleur ou ex æquo sur 17 cas sur 18. Gain sur Greedy du meilleur solveur : 1,4–5,0 % (équilibré),
  0,4–3,1 % (priorité accueil), 2,8–7,9 % (priorité personnel). Naïve est 4,6–13,9 % au-dessus de Greedy.
- Priorité accueil : MILP = CP-SAT partout, à 0,1 % ou moins de la borne ; les refus restants sont imposés par les lits.
- Priorité personnel : CP-SAT réduit le déficit RH mais refuse beaucoup plus (113 contre 73 en S4). MILP y est peu fiable
  (pire que Greedy en S0 et S3, gap 17–19 %).
- Le **déficit RH** domine l'objectif équilibré (75 à 95 %). Un meilleur objectif n'est pas toujours un meilleur accueil.
- Le taux de couverture de la demande (≈ 99 % en S0) ne dit rien du personnel : 41 à 51 % des postes cibles sont couverts en S0 (équilibré).
- Personnel en deux viviers disjoints, {URG, CHI} et {REA, MED} : URG ne peut prendre du personnel qu'à CHI.
Ne pas réintroduire de warm start Greedy dans CBC : il s'y bloque et rend exactement la baseline.
