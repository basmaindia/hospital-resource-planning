# Formulation mathématique et unités

## Statut

Ce document décrit la formulation **réellement codée** dans `src/hospital_planning/optimization/` (`naive.py`, `greedy.py`, `exact.py`, `objective.py`, `validator.py`). Il ne constitue pas une recommandation clinique ou réglementaire. Tous les coefficients et ratios sont synthétiques et configurables dans `configs/hospital.json`. Les écarts assumés avec un hôpital réel sont listés dans « Hypothèses et limites ».

## Unités

| Variable | Unité | Signification |
|---|---:|---|
| `requested_admissions` | patients/jour | Demande d'admissions : plafond entier de la prévision, `ceil(yhat)` |
| `accepted_admissions` | patients/jour | Admissions effectivement acceptées par le plan |
| `rejected_admissions` | patients | Admissions non acceptées sur l'horizon |
| `occupancy` | patients ou lits occupés | Recensement de fin de journée, identique aux trois postes dans l'approximation journalière |
| `opened_beds` | lits/jour | Lits ouverts par le plan au jour considéré |
| `unmet_patient_days` | journées-patients | Écart d'occupation entre demande complète et demande soutenue |
| `staff_required` / `staff_assigned` | professionnels/poste | Besoin et couverture par rôle, service, jour et poste |

`capacity_available` est le plafond physique de l'instance : `beds_total` du service en S0, réduit par les scénarios de fermeture. `opened_beds` est la décision.

## Ensembles et paramètres

Ensembles : services `S`, jours `T` (7 jours), postes `K` (matin, soir, nuit), rôles `R`, professionnels actifs `I`.

| Symbole | Signification | Source |
|---|---|---|
| `req[s,t]` | admissions demandées | instance (scénario compris) |
| `occ[s,t]` | occupation si toute la demande est acceptée | instance |
| `start[s]` | recensement au début de l'horizon | instance |
| `dis[s,t]` | sorties prévues si toute la demande est acceptée | instance |
| `cap[s,t]` | lits disponibles | instance |
| `los[s]` | durée de séjour entière et déterministe | `length_of_stay_days` |
| `ratio[r]` | effectif cible pour dix lits ouverts et par poste | `staff_per_ten_beds` |
| `min[r]` | effectif minimal par poste d'un service ouvert | `minimum_staff_by_role` |
| `avail[i,t,k]`, `qual[i,s]`, `max[i]` | disponibilité, qualification, nombre maximal de postes | données du personnel |

## Dynamique des patients

Les sorties sont traitées avant les admissions. Pour chaque service `s` et jour `t` :

`occ[s,t] = start[s] − Σ(j ≤ t) dis[s,j] + Σ(j ≤ t) req[s,j]`.

Un patient refusé au jour `j` aurait occupé un lit de `j` à `j + los[s] − 1`. L'occupation soutenue `O` est donc :

`O[s,t] + Σ (req[s,j] − A[s,j]) = occ[s,t]`, pour `j` de `max(1, t − los[s] + 1)` à `t`.

Les sorties soutenues au jour `t` valent `dis[s,t] − (req − A)[s, t − los[s]]` : un patient refusé ne sort pas. Les admissions refusées et les journées-patients non soutenues sont deux métriques distinctes.

## Variables de décision

| Variable | Domaine | Signification |
|---|---|---|
| `A[s,t]` | entier, `0 ≤ A ≤ req[s,t]` | admissions acceptées |
| `O[s,t]` | entier, `0 ≤ O ≤ occ[s,t]` | occupation soutenue |
| `L[s,t]` | entier, `0 ≤ L ≤ cap[s,t]` | lits ouverts |
| `Y[s,t]` | binaire | 1 si le service est ouvert |
| `X[i,s,t,k]` | binaire | affectation, créée seulement si `avail[i,t,k] = 1` et `qual[i,s] = 1` |
| `Q[s,t,k,r]` | entier ≥ 0 | déficit par rapport à la cible de personnel |
| `Wmin[r]`, `Wmax[r]` | entier ≥ 0 | charge minimale et maximale du rôle `r`, en postes |

La demande non soutenue n'est pas une variable : `D[s,t] = occ[s,t] − O[s,t]`.

## Contraintes dures

1. **Dynamique** : l'égalité de cohortes ci-dessus.
2. **Lits** : `O[s,t] ≤ L[s,t] ≤ cap[s,t] × Y[s,t]` et `L[s,t] ≥ Y[s,t]`.
3. **Dotation minimale d'un service ouvert** : `Σ(i de rôle r) X[i,s,t,k] ≥ min[r] × Y[s,t]`. Le minimum est de 1 par rôle et par poste ; il ne dépend pas du nombre de lits.
4. **Cible de personnel** : `10 × (Σ(i de rôle r) X[i,s,t,k] + Q[s,t,k,r]) ≥ ratio[r] × L[s,t]`.
5. **Un poste par jour** : `Σ(s,k) X[i,s,t,k] ≤ 1`.
6. **Nombre de postes** : `Σ(s,t,k) X[i,s,t,k] ≤ max[i]`.
7. **Repos** : deux postes de jours consécutifs sont incompatibles si moins de `min_rest_hours` (11 h) les sépare.
8. **Nuits** : au plus `max_consecutive_nights` (3) nuits consécutives, sur toute fenêtre de 4 jours de l'horizon.
9. **Charges** : `Wmin[r] ≤ charge[i] ≤ Wmax[r]` pour tout professionnel actif et présent `i` de rôle `r`.

La politique `shortage_permitting`, utilisée par défaut, n'assouplit que la cible (4), par `Q`. La politique `strict` ajoute `A = req` et `Q = 0`.

## Frontières de l'horizon

Les sept jours sont planifiés comme une fenêtre isolée :

- **Début, patients** : l'occupation initiale est prise en compte. Les cohortes admises avant l'horizon et encore présentes sont reconstruites depuis l'historique (`start` et `dis`).
- **Début, personnel** : aucune affectation antérieure n'est connue. Le repos entre la veille de l'horizon et le premier jour, les nuits déjà enchaînées et les postes déjà effectués dans la semaine **ne sont pas contrôlés**. Les contraintes 6 à 8 ne portent que sur les jours de l'horizon.
- **Fin, personnel** : rien n'est imposé après le septième jour.
- **Fin, patients** : un refus n'est pénalisé que pour les journées comprises dans l'horizon. Refuser au dernier jour coûte une journée-patient, quelle que soit la durée de séjour ; les derniers jours sont donc relativement moins protégés.

## Objectif

Minimiser :

`c_lit × Σ L[s,t] + Σ c_dem[s] × D[s,t] + Σ c_ref[s] × (req − A)[s,t] + Σ c_rh[s] × Q[s,t,k,r] + c_eq × Σ(r) (Wmax[r] − Wmin[r])`.

Les coefficients sont des entiers fixés par un **profil de pondération** (`configs/profiles.json`). Les multiplicateurs par service valent 1 sauf mention contraire.

| Coefficient | Champ | `equilibre` | `priorite_accueil` | `priorite_personnel` |
|---|---|---:|---:|---:|
| `c_lit`, par lit-jour ouvert | `opened_bed` | 10 | 10 | 10 |
| `c_dem`, par journée-patient non soutenue | `unmet_patient_day` | 1000 | 3000 (URG ×3) | 1000 |
| `c_ref`, par admission refusée | `rejected_admission` | 0 | 5000 (URG ×3) | 0 |
| `c_rh`, par poste cible non couvert | `staff_target_shortage` | 500 | 500 (URG ×2) | 750 |
| `c_eq`, par poste d'étendue de charge | `workload_imbalance` | 1 | 1 | 100 |

Ces valeurs sont des hypothèses de démonstration. Le profil `equilibre` reprend les poids de `hospital.json`. Les objectifs de deux profils ne sont pas comparables entre eux : on compare leurs KPI. Le champ `priority` d'un service n'intervient pas dans l'objectif ; il ne sert qu'à Greedy, pour l'ordre de traitement du personnel (REA, URG, CHI, MED). Toutes les méthodes d'un profil sont évaluées avec le même objectif, recalculé depuis les tables retournées.

Conséquences à connaître, avec le profil `equilibre` :

- dix lits ouverts demandent 12 postes cibles par jour. Sans personnel disponible, un lit coûte donc en moyenne 610 (10 + 1,2 × 500), moins que les 1000 d'une journée-patient refusée : accueillir reste préférable **en moyenne** ;
- mais la cible est arrondie au-dessus. Passer de 5 à 6 lits ajoute 3 postes infirmiers (1 510 avec le lit), et passer de 10 à 11 lits ajoute 9 postes (4 510) : refuser un patient pour rester sous un palier devient avantageux. C'est l'essentiel des refus supplémentaires de CP-SAT en S0 (14 au lieu de 4) : sur les 11 services-jours où il ouvre un nombre de lits différent de Greedy, 7 se terminent sur un multiple de 5 ;
- le plafond de personnel rend le déficit RH incompressible pour l'essentiel : il représente 75 à 95 % de l'objectif sur S0–S5.

## Équité

Les groupes comparables sont les professionnels **actifs et présents du même rôle**. Pour chaque rôle, l'étendue est `max(charge) − min(charge)` ; `workload_range` est la somme des étendues. Seuls comptent les **présents**, c'est-à-dire disponibles à au moins un poste de l'horizon. Un présent sans affectation compte avec une charge nulle ; un agent absent sur tout l'horizon (S3, S4) est exclu, sinon l'étendue resterait au plafond quelle que soit la méthode. Un agent présent une partie de l'horizon reste compté. Le validateur recalcule cette valeur indépendamment.

## Méthodes

- **Naïve** : sert de point de comparaison bas. Chaque jour, un taux d'acceptation unique (lits libres de l'hôpital / demande, au plus 1) s'applique à tous les services, dans la limite de leurs lits. Pour le personnel, après la dotation minimale obligatoire, chaque besoin reçoit la même fraction de sa cible (répartition aux plus forts restes de la capacité hebdomadaire du rôle). Aucun service n'est prioritaire et les postes qu'un service ne peut pas pourvoir ne sont pas redistribués.
- **Greedy** : chaque jour et service, applique les sorties, accepte autant d'admissions que de lits libres et ouvre exactement les lits occupés. Il affecte ensuite le personnel en deux passes, dotation minimale puis cible, dans l'ordre date, priorité du service, poste, rôle, et choisit le premier professionnel admissible par identifiant. Il ne refuse jamais un patient pour réduire le déficit RH.
- Naïve et Greedy ne lisent pas les poids : leur plan est identique pour tous les profils, seule leur évaluation change.
- **MILP/CBC** et **CP-SAT** : résolvent la formulation ci-dessus avec les poids du profil dans un budget de temps. Voir [exact_solvers.md](exact_solvers.md).

## KPI

- `rejected_admissions` est un KPI en patients, sans coût propre avec `equilibre` et `priorite_personnel` : la demande n'y est pénalisée que par les journées-patients non soutenues. Seul `priorite_accueil` ajoute un coût par refus, qui corrige aussi l'effet de fin d'horizon.
- `coverage_rate` = occupation soutenue / occupation demandée. Il mesure l'accueil, pas le personnel. Si l'occupation demandée est nulle, le code retourne 1 par convention.
- `staff_shortage_total` = Σ `max(cible − affectés, 0)`, avec une cible entière `max(min[r], ceil(ratio[r] × L / 10))` pour un service ouvert.
- `optimality_gap` = (objectif − borne) / objectif, lorsqu'un solveur fournit une borne.

## Validation indépendante

Le validateur recompte, depuis les tables retournées et sans réutiliser les contraintes des solveurs : capacité et bilan des lits, `0 ≤ acceptées ≤ demandées`, cohortes rejouées depuis l'instance, disponibilité, qualification, double affectation, nombre de postes, repos, nuits consécutives et dotation minimale. Le déficit de cible est compté à part : il n'invalide une solution que sous la politique `strict`.

## Hypothèses et limites

- Dans les données synthétiques, les qualifications forment deux viviers disjoints : {URG, CHI} et {REA, MED}. Aucun agent ne peut passer de l'un à l'autre ; donner la priorité à URG ne peut donc prendre du personnel qu'à CHI. MED ne peut être pourvu que par les agents aussi qualifiés en REA.
- La durée de séjour est fixe et déterministe par service ; aucun transfert entre services n'est modélisé.
- L'occupation est journalière : les pics dans la journée ne sont pas représentés.
- Les heures contractuelles (`contracted_hours`) ne sont pas une contrainte. La charge est limitée en nombre de postes (`max_shifts` = 5, soit 40 h avec des postes de 8 h). Les heures supplémentaires ne sont pas modélisées.
- La disponibilité future recopie la dernière disponibilité observée le même jour de semaine et au même poste.
- Ouvrir un lit n'exige que la dotation minimale du service : un lit peut donc être ouvert avec un effectif très inférieur à sa cible.
- Si l'occupation incompressible (patients déjà présents) dépasse la capacité d'un scénario, les solveurs exacts sont infaisables et Greedy est déclaré invalide par le validateur.
