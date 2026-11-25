# Solveurs exacts et comparabilité — phase 6

Les adaptateurs `milp` (PuLP/CBC) et `cp_sat` (OR-Tools) consomment la même instance opérationnelle, la même projection déterministe de disponibilité et la même configuration que Greedy.

## Formulation commune

Les deux modèles décident les admissions acceptées, l'occupation soutenue, les lits ouverts, les affectations individuelles et le déficit de cible RH. Ils imposent identiquement : capacité, dynamique de cohortes, disponibilité, qualifications, un poste par jour, maximum de postes, repos minimal, nuits consécutives et dotation minimale par rôle/poste pour chaque lit ouvert.

La cible RH est linéarisée par `10 × (assigned_staff + shortage) ≥ ratio × opened_beds`; la dotation minimale est imposée séparément. Sous `shortage_permitting`, seul `shortage` est souple. La politique stricte impose à la fois toutes les admissions et un déficit de cible nul.

L'équité est la somme, par rôle, des étendues de charge parmi tous les professionnels actifs, y compris ceux sans affectation. Pour chaque rôle, les solveurs créent `load_min` et `load_max`, encadrent chaque charge individuelle, puis minimisent `load_max - load_min`. Le validateur recalcule cette valeur à partir des affectations retournées.

## Objectif canonique et statuts

Les méthodes exposent les composantes `opened_bed_cost`, `unmet_patient_day_cost`, `staff_target_shortage_cost`, `workload_imbalance_cost` et `total_cost`. Les admissions refusées restent un KPI sans pénalité propre, afin de ne pas compter deux fois la même demande non soutenue.

Une solution `FEASIBLE` obtenue à la limite de temps est conservée et validée; elle n'est jamais présentée comme optimale. Si un solveur ne trouve aucune solution dans son budget, son statut est `UNKNOWN` et aucun KPI n'est publié.

## Budget de calcul

`configs/hospital.json` (`planning_policy`) fixe le même budget pour les deux solveurs : `solver_time_limit_seconds` = 50 s et `solver_num_workers` = 8 threads. Un scénario complet (Greedy, MILP et CP-SAT) reste sous 2 minutes sur un poste à 8 threads. Le budget peut être remplacé sans modifier la configuration :

- ligne de commande : `--time-limit 20 --workers 4` sur `hospital_planning.experiments.runner`;
- API : champs optionnels `solver_time_limit_seconds` (1 à 600) et `solver_num_workers` (1 à 64) de `POST /api/v1/jobs/experiments`.

Chaque `method_result.json` et chaque ligne de `metrics.csv` conserve le budget réellement appliqué.

## Point de départ, borne et écart d'optimalité

- **MILP/CBC** démarre sans solution initiale. Avec la solution Greedy en *warm start*, CBC n'en sortait pas et rendait exactement la baseline.
- **CP-SAT** reçoit la solution Greedy comme indice (*hint*), puis cherche en parallèle sur plusieurs threads.
- `best_bound` est la meilleure borne inférieure prouvée. Pour CBC, elle est lue dans son journal (« best possible ») et corrigée du terme constant de l'objectif. `optimality_gap = (objectif − borne) / objectif`.
- CBC peut s'arrêter sur une assertion interne (bibliothèque CLP) selon sa graine, par exemple S4 avec le profil `priorite_personnel` et la graine 42. Il est alors relancé avec la graine suivante, dans le temps restant ; `solver_seed` enregistre la graine réellement utilisée.
- `OPTIMAL` n'est déclaré pour CBC que si sa recherche est terminée. Interrompu au nœud racine, CBC peut annoncer « Optimal solution found » pour une simple solution courante : ce cas est enregistré `FEASIBLE` / `OptimalNotProven`.

La recherche parallèle limitée par le temps n'est pas strictement déterministe : relancer CP-SAT peut donner une valeur légèrement différente. Greedy reste déterministe.

## Déficit structurel S0

La cible S0 représente 2 322 affectations et les plafonds contractuels bruts représentent au plus 1 175 affectations (50 médecins × 5, 110 infirmiers × 5, 75 aides-soignants × 5). Avant disponibilités, qualifications, repos et nuits, le déficit structurel minimal est donc 1 147 postes-cibles. Les effectifs et cibles synthétiques ne sont pas modifiés pour améliorer ce résultat.

## Exécution

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m hospital_planning.optimization.exact
```

Les sorties sont écrites dans `results/allocations/milp/S0/` et `results/allocations/cp_sat/S0/`, avec les mêmes fichiers que Greedy et un `method_result.json` traçable.
