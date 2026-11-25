# Outil de planification des ressources hospitalières

Prototype reproductible de planification hospitalière fondé exclusivement sur des données synthétiques. Il relie la demande d’admissions, les besoins en lits et en personnel, l’optimisation, des scénarios de stress, une API FastAPI et un dashboard Next.js. Il ne constitue ni une recommandation clinique, ni un outil réglementaire, ni un système de décision de soins.

Les exigences de référence sont dans [specifications.md](specifications.md). La feuille de route est dans [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) et l'état réel du travail dans [PROGRESS.md](PROGRESS.md).

## Fonctionnalités disponibles

- Données synthétiques reproductibles pour URG, MED, REA et CHI.
- Prévisions J+1 à J+7 avec cinq modèles et validation chronologique.
- Instance commune de besoins opérationnels, puis stratégie naïve, Greedy, MILP/CBC et CP-SAT avec validateur indépendant et trois profils de pondération.
- Scénarios S0 à S5, expériences persistées, API FastAPI et dashboard à dix vues, dont un simulateur de scénario personnalisé.

Les allocations et comparaisons ne sont affichées que lorsqu’elles ont été effectivement générées et persistées.

## Architecture

```text
Données synthétiques → Prévisions → Besoins opérationnels
       → Optimisation → Scénarios / expériences → API → Dashboard
```

Technologies : Python, pandas, Pydantic, FastAPI, PuLP/CBC, OR-Tools, Next.js 15, React, TypeScript, ESLint et Playwright.

## Installation sous Windows

Cloner le dépôt publié, puis exécuter depuis sa racine :

```powershell
git clone <URL_DU_DEPOT>
Set-Location <DOSSIER_DU_DEPOT>
```

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install . pytest pytest-cov ruff httpx
Set-Location frontend
npm.cmd install
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

Le chemin actuel contient un caractère accentué. Sous Windows, l'installation Python non éditable est utilisée pour éviter une limite d'encodage du mécanisme éditable. Après une modification Python, relancer `pip install --force-reinstall --no-deps .` depuis la racine du projet.

La structure utile est : `configs/` (paramètres), `data/` (données synthétiques), `results/` (artefacts), `src/` (backend), `frontend/` (dashboard), `tests/` et `docs/`. Le dépôt inclut un jeu de démonstration sélectionné ; les autres sorties locales restent ignorées par Git.

## Régénérer les données synthétiques (facultatif)

Le dashboard peut démarrer avec les artefacts fournis sans recalcul. Pour régénérer les données après installation Python, exécuter depuis la racine :

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m hospital_planning.data.generator
```

Les données et le rapport de qualité sont créés dans `data/synthetic/`. Elles sont reproductibles pour une configuration et une graine identiques.

## Évaluer les prévisions

Après la génération des données :

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m hospital_planning.forecasting.evaluation
```

Les prévisions J+1 à J+7, les métriques et la sélection de modèle par service sont écrites dans `results/forecasts/`. Consulter [docs/forecasting.md](docs/forecasting.md) pour le protocole et les limites.

## Construire les besoins opérationnels

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m hospital_planning.operational.requirements
```

Cette commande produit l'instance canonique dans `results/operational_instances/S0/`, sans prendre de décision d'allocation ou de planning. Elle fonctionne directement avec les prévisions fournies. Changer les solveurs ou les poids de l'objectif ne les périme pas ; après une modification des services, des données synthétiques, des postes, de la graine ou de l'horizon, relancer d'abord le générateur et les prévisions (environ 35 s), sinon la commande s'arrête avec un message explicite. Voir [docs/operational_requirements.md](docs/operational_requirements.md).

## Exécuter la baseline gloutonne

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m hospital_planning.optimization.greedy
```

La baseline et son validateur indépendant écrivent leurs résultats dans `results/allocations/greedy/S0/`. Voir [docs/greedy_and_validator.md](docs/greedy_and_validator.md).

## Exécuter les solveurs exacts

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m hospital_planning.optimization.exact
```

Les solveurs MILP/CBC et CP-SAT utilisent la même instance S0 et écrivent leurs artefacts dans `results/allocations/milp/S0/` et `results/allocations/cp_sat/S0/`. Voir [docs/exact_solvers.md](docs/exact_solvers.md).

## Exécuter les scénarios

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m hospital_planning.experiments.runner
```

La commande crée les expériences Greedy S0–S5 dans `results/experiments/`. Ajouter `--methods naive greedy milp cp_sat --profiles equilibre priorite_accueil priorite_personnel` pour comparer les quatre méthodes et les trois profils (≈ 106 s par scénario et par profil, ≈ 32 min au total, PC branché et sans mise en veille). Le budget par solveur exact, 50 s et 8 threads par défaut, se règle dans `configs/hospital.json` ou avec `--time-limit` et `--workers`. Le manifeste de sensibilité à 80 scénarios s'obtient avec `--sensitivity-manifest` et se calcule avec `python -m hospital_planning.experiments.sensitivity` (≈ 100 s en Naïve et Greedy). Voir [docs/experiments.md](docs/experiments.md).

## Démarrer l'API locale

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m uvicorn hospital_planning.api.app:app --reload --host 127.0.0.1 --port 8000
```

La documentation interactive est disponible sur `http://127.0.0.1:8000/docs`. L'API permet de soumettre explicitement des jobs d'expérience, de consulter leur état et de télécharger les résultats déjà produits. Voir [docs/api_contract.md](docs/api_contract.md).

Pour exécuter la vérification HTTP complète sur un poste local autorisant les sockets :

```powershell
.\scripts\verify_api.ps1
```

## Démarrer le dashboard

Dans un second terminal, après avoir démarré l'API :

```powershell
Set-Location frontend
npm.cmd run dev
```

Le dashboard est disponible sur `http://localhost:3011`. Après clonage et installation, ses vues lisent les artefacts fournis sans exécuter le pipeline. La vue Expériences peut soumettre explicitement un nouveau calcul après clic utilisateur. Copier éventuellement `frontend/.env.example` vers `frontend/.env.local` pour expliciter l'URL API locale. Consulter [docs/dashboard.md](docs/dashboard.md) pour la connexion API et les limites.

## Résultats de référence

Objectif du profil, plus bas = meilleur (graine 42, 50 s et 8 threads par solveur exact). Les objectifs ne se comparent qu'au sein d'un profil. Refus et déficit RH : meilleure méthode (Greedy entre parenthèses). Détail et lecture dans [PROGRESS.md](PROGRESS.md).

**Équilibré**

| Scénario | Naïve | Greedy | MILP/CBC | CP-SAT | Meilleure | vs Greedy | Refus | Déficit RH |
|---|---:|---:|---:|---:|---|---:|---:|---:|
| S0 nominal | 718 885 | 636 379 | 609 870 | **604 800** | CP-SAT | −5,0 % | 9 (4) | 1 123 (1 200) |
| S1 pic URG | 787 965 | 695 559 | 666 041 | **661 490** | CP-SAT | −4,9 % | 33 (29) | 1 138 (1 218) |
| S2 hausse +25 % | 1 010 265 | 924 327 | 903 320 | **900 740** | CP-SAT | −2,6 % | 76 (73) | 1 345 (1 408) |
| S3 absences 15 % | 783 385 | 712 876 | 696 200 | **691 790** | CP-SAT | −3,0 % | 9 (4) | 1 295 (1 353) |
| S4 crise combinée | 1 083 265 | 1 002 325 | **988 260** | 988 270 | MILP/CBC | −1,4 % | 73 (73) | 1 524 (1 564) |
| S5 fermeture 10 % lits | 757 455 | 674 469 | 650 444 | **641 250** | CP-SAT | −4,9 % | 35 (26) | 988 (1 096) |

**Priorité accueil**

| Scénario | Naïve | Greedy | MILP/CBC | CP-SAT | Meilleure | vs Greedy | Refus | Déficit RH |
|---|---:|---:|---:|---:|---|---:|---:|---:|
| S0 nominal | 964 385 | 846 879 | **820 370** | **820 370** | MILP/CBC = CP-SAT | −3,1 % | 4 (4) | 1 147 (1 200) |
| S1 pic URG | 1 847 465 | 1 690 059 | **1 657 550** | **1 657 550** | MILP/CBC = CP-SAT | −1,9 % | 29 (29) | 1 159 (1 218) |
| S2 hausse +25 % | 2 714 265 | 2 576 327 | **2 555 320** | **2 555 320** | MILP/CBC = CP-SAT | −0,8 % | 73 (73) | 1 366 (1 408) |
| S3 absences 15 % | 1 040 885 | 945 876 | **930 370** | **930 370** | MILP/CBC = CP-SAT | −1,6 % | 4 (4) | 1 322 (1 353) |
| S4 crise combinée | 2 800 765 | 2 676 825 | **2 665 320** | **2 665 320** | MILP/CBC = CP-SAT | −0,4 % | 73 (73) | 1 541 (1 564) |
| S5 fermeture 10 % lits | 1 402 455 | 1 260 469 | **1 233 460** | **1 233 460** | MILP/CBC = CP-SAT | −2,1 % | 26 (26) | 1 042 (1 096) |

**Priorité personnel**

| Scénario | Naïve | Greedy | MILP/CBC | CP-SAT | Meilleure | vs Greedy | Refus | Déficit RH |
|---|---:|---:|---:|---:|---|---:|---:|---:|
| S0 nominal | 1 061 620 | 937 270 | 999 970 | **865 660** | CP-SAT | −7,6 % | 27 (4) | 1 045 (1 200) |
| S1 pic URG | 1 135 200 | 1 000 950 | 963 100 | **928 710** | CP-SAT | −7,2 % | 61 (29) | 1 045 (1 218) |
| S2 hausse +25 % | 1 403 250 | 1 277 020 | 1 237 200 | **1 223 760** | CP-SAT | −4,2 % | 103 (73) | 1 264 (1 408) |
| S3 absences 15 % | 1 158 370 | 1 051 720 | 1 187 540 | **997 810** | CP-SAT | −5,1 % | 32 (4) | 1 208 (1 353) |
| S4 crise combinée | 1 512 750 | 1 393 820 | 1 361 520 | **1 354 380** | CP-SAT | −2,8 % | 113 (73) | 1 421 (1 564) |
| S5 fermeture 10 % lits | 1 073 440 | 949 360 | 887 690 | **874 750** | CP-SAT | −7,9 % | 75 (26) | 871 (1 096) |

## Limites

- Les données, ratios, scénarios et résultats sont synthétiques.
- Les expériences fournies couvrent S0–S5 avec quatre méthodes et trois profils (72 résultats respectant toutes les contraintes dures, un seul cas prouvé optimal ; 33 à 60 % des postes cibles couverts). MILP et CP-SAT, parallèles et limités à 50 s, peuvent varier légèrement d'une exécution à l'autre.
- Le déficit de personnel représente 75 à 95 % de l'objectif équilibré : un meilleur objectif peut s'accompagner de davantage d'admissions refusées.
- Les solveurs exacts et la sensibilité exhaustive peuvent être coûteux et ne sont jamais lancés automatiquement.
- Le test Playwright nécessite un navigateur installé et ne contrôle pas les données affichées.

## Vérification et documentation

Depuis la racine :

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check src tests
Set-Location frontend
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
npm.cmd run test
```

Documentation complémentaire : [modèle mathématique](docs/mathematical_model.md), [données](docs/synthetic_data.md), [prévisions](docs/forecasting.md), [optimisation](docs/exact_solvers.md), [scénarios](docs/experiments.md), [API](docs/api_contract.md), [dashboard](docs/dashboard.md), [dictionnaire de données](docs/data_dictionary.md) et [état du projet](PROGRESS.md).
