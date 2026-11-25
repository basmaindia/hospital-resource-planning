# Dashboard local — phase 9

## Objet et périmètre

Le dashboard Next.js présente les résultats déjà calculés du prototype sur des données exclusivement synthétiques. Les lectures ne génèrent ni donnée ni solveur. La vue Expériences peut toutefois soumettre explicitement un job après action de l’utilisateur ; aucune soumission ne survient au chargement.

Neuf vues sont disponibles dans une navigation latérale : les huit prévues par le cahier des charges et la comparaison des scénarios.

1. vue d’ensemble ;
2. comparaison des scénarios (toutes les méthodes sur S0–S5) ;
3. exploration des données ;
4. prévisions ;
5. allocation des ressources ;
6. comparaison des méthodes ;
7. scénarios ;
8. analyse de sensibilité ;
9. expériences et export.

Le dashboard ne contient aucune série de prévision, allocation, KPI ou paramètre de scénario codé en dur. Il lit les artefacts persistés via l'API. Si une phase productrice n'a pas généré l'artefact requis, la vue concernée affiche un état vide explicite ; elle ne présente pas d'exemple comme un résultat calculé.

## Connexion à l’API

Par défaut, le navigateur lit l’API sur `http://127.0.0.1:8000`. L’URL peut être remplacée sans modifier le code :

```powershell
$env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:8000"
```

Lorsque l’API est joignable, le dashboard charge les scénarios configurés, les séries d'exploration, les prévisions, l'instance opérationnelle nominale, le registre et l'allocation de l'expérience sélectionnée. Les résultats de crise proviennent des expériences persistées, pas d'une instance opérationnelle autonome par scénario. Lorsque l’API ou un artefact est indisponible, il affiche l'erreur ou l'état vide reçu ; il ne fabrique pas de résultat ni ne relance un job.

Le filtre Service est alimenté prioritairement par les services des séries historiques synthétiques, puis par les prévisions si les historiques ne sont pas disponibles. Il ne dépend donc pas d'une instance opérationnelle qui pourrait manquer pour un scénario de crise. L'instance nominale `S0`, déjà produite par la phase 4, est explicitement accessible via l'identifiant de scénario `S0_BASELINE`.

Le filtre global « Résultat » est une lecture : il ne propose que les méthodes réellement persistées pour l'expérience sélectionnée. La vue Expériences possède séparément le choix « Algorithme à exécuter », qui propose Greedy, MILP/CBC et CP-SAT et exige un clic explicite avant toute soumission.

Les téléchargements restent sous la responsabilité de l’API :

```text
GET /api/v1/experiments/{experiment_id}/downloads/{artifact_path}
```

L’API vérifie le chemin de l’artefact avant de répondre. Le lien « CSV lits » de la vue Expériences télécharge les allocations de lits d’une méthode ; les autres fichiers (affectations, couverture, disponibilités) sont accessibles par l’API.

## Analyse de sensibilité

Le manifeste de sensibilité contient 80 instances et 160 appels exacts potentiels. Il est affiché à titre déclaratif ; les expériences correspondantes ne sont pas considérées comme exécutées tant que leurs artefacts ne sont pas persistés. Aucune courbe, heatmap ou frontière de Pareto chiffrée n’est inventée.

## État fonctionnel final de la phase 9

- Les vues Vue d'ensemble, Exploration, Prévisions, Allocation et Scénarios lisent des données réellement persistées. Les admissions entières de la vue Prévisions viennent de l'instance opérationnelle (plafond de `yhat`).
- La vue Comparaison scénarios possède un sélecteur de profil de pondération et affiche ses poids. Elle retient une expérience par scénario pour ce profil, avec la graine de référence en priorité. Elle compare huit indicateurs et affiche l'écart à S0, le gap et le budget des solveurs.
- La vue Méthodes compare les KPI seulement lorsque plusieurs méthodes sont présentes dans une même expérience ; sinon elle explique comment obtenir une comparaison valide.
- La vue Expériences soumet explicitement un job, suit son état, recharge le registre après `COMPLETED`, affiche ses KPI et propose les exports existants.
- La vue Sensibilité lit le manifeste réel, son volume et son coût exact estimé, mais ne dessine aucun résultat avant une exécution explicitement persistée.

## Interactions disponibles

La vue Expériences permet de choisir un scénario et une méthode, puis de soumettre explicitement un job via l'API. Elle suit uniquement les états réellement définis par le backend (`QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`) et actualise le registre après confirmation `COMPLETED`. Aucune soumission n'a lieu au chargement de l'application.

La table détaille les KPI persistés et propose un lien de téléchargement vers l'artefact CSV des lits. Les graphiques existants restent alimentés par les réponses de lecture passives. Les comparaisons multi-méthodes ne combinent que des métriques réellement retournées par une expérience sélectionnée.

Les quatre filtres du haut restent visibles partout, mais ne s'appliquent pas à toutes les vues : Service (Exploration, Prévisions, Allocation), Scénario (Vue d'ensemble, Allocation, Méthodes, Scénarios, Expériences), Résultat et Expérience (Vue d'ensemble, Allocation, Méthodes). La comparaison des scénarios et la sensibilité n'en utilisent aucun.

Les filtres de résultats sont liés : un changement de scénario limite les expériences à ce scénario, un changement d'expérience adapte les méthodes disponibles, et une méthode absente produit un message explicite plutôt qu'une requête incohérente. Une erreur réseau reste une erreur visible (« API inaccessible »), distincte d'un artefact non généré (404) ou d'une combinaison sans expérience.

Le changement de scénario relit l'allocation de l'expérience correspondante ; l'instance opérationnelle affichée reste celle de S0. Une réponse arrivée après une nouvelle sélection est ignorée : une réponse lente ne peut pas remplacer les données liées au filtre courant.

## Lancer localement

Dans un terminal, depuis la racine du projet :

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m uvicorn hospital_planning.api.app:app --reload --host 127.0.0.1 --port 8000
```

Dans un deuxième terminal :

```powershell
Set-Location frontend
npm.cmd run dev
```

Ouvrir ensuite `http://localhost:3011`. Le script `npm.cmd run dev` fixe ce port, partagé avec Playwright. Les origines CORS autorisées par défaut sont `http://localhost:3011` et `http://127.0.0.1:3011`; les origines 3000 sont conservées pour compatibilité. Pour une autre origine locale, configurer explicitement `HOSPITAL_CORS_ORIGINS` avant de démarrer FastAPI ; le joker `*` est refusé.

## Contrôles

Les commandes de contrôle frontend sont :

```powershell
Set-Location frontend
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

Le test navigateur `frontend/tests/dashboard.spec.ts` couvre l’ouverture de huit des neuf vues (toutes sauf Comparaison scénarios), le filtre Service et l’absence de calcul automatique pendant la navigation. Il ne contrôle pas les données affichées. Installer Chromium une seule fois, puis l’exécuter sur un poste local autorisant `localhost` :

```powershell
Set-Location frontend
npx.cmd playwright install chromium
npm.cmd run test
```

Les tests navigateur nécessitent un serveur Next.js local et un navigateur installé pour Playwright.
