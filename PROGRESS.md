# État du projet

Dernière synthèse : novembre 2026. Ce fichier décrit l’état observable du projet ; les exigences restent dans `specifications.md` et la feuille de route approuvée dans `IMPLEMENTATION_PLAN.md`.

## Phases réalisées

| Phase | Livraison principale | État |
|---|---|---|
| 1 | Contrats de domaine, configuration, formulation mathématique et fondations | Implémentée |
| 2 | Données hospitalières synthétiques reproductibles | Implémentée |
| 3 | Prévisions J+1 à J+7 et validation chronologique | Implémentée |
| 4 | Instance canonique de besoins opérationnels | Implémentée |
| 5 | Baseline Greedy et validateur indépendant | Implémentée |
| 6 | Solveurs MILP/CBC et CP-SAT, objectif commun | Implémentée |
| 7 | Scénarios, expériences et manifeste de sensibilité | Implémentée |
| 8 | API FastAPI, jobs et téléchargements sécurisés | Implémentée |
| 9 | Dashboard Next.js relié aux artefacts API | Implémentée, validation locale finale requise |

## Fonctionnalités disponibles

- Génération de données synthétiques pour URG, MED, REA et CHI.
- Cinq modèles de prévision, sélection chronologique par service et prévisions finales de sept jours.
- Traduction des prévisions en besoins de lits et de personnel.
- Greedy, MILP/CBC et CP-SAT avec objectif canonique et validateur indépendant.
- Scénarios S0–S5, résultats d’expériences et manifeste de sensibilité de 80 combinaisons.
- API FastAPI sur le port 8000 : lectures, jobs explicitement soumis et téléchargements contrôlés.
- Dashboard sur le port 3011 : neuf vues, filtres, consultation des résultats et lancement manuel d’une méthode.

## Résultats et validations confirmés

- Les données et Greedy sont reproductibles pour une configuration et une graine identiques. MILP et CP-SAT, parallèles et limités en temps, peuvent varier légèrement d'une exécution à l'autre.
- La validation de prévision réserve le test final ; il n’intervient pas dans la sélection des modèles.
- Les trois méthodes utilisent les mêmes conventions d’unités et les mêmes composantes d’objectif.
- Les admissions refusées sont un KPI en patients ; la pénalité de demande est portée une seule fois par les journées-patients non soutenues.
- Contrôles confirmés le 25 novembre 2026 : `pytest -q` (61 tests), `ruff check src tests`, `npm.cmd run typecheck` et `npm.cmd run lint`. `npm.cmd run build` et Playwright (avec Edge) ont réussi lors de l'audit, avant ces corrections.

## Jeu de démonstration pour GitHub

Le dépôt sélectionne 79 fichiers d'artefacts, soit 34 173 770 octets (32,59 Mio) : les données synthétiques complètes, six fichiers de prévision, l'instance opérationnelle S0, le manifeste de sensibilité et six expériences persistées (S0/Greedy, S1/MILP, S2/Greedy, S3/Greedy, S4/Greedy, S5/CP-SAT). Les chemins de métadonnées de ces expériences sont relatifs au projet. Un test de lecture depuis un autre dossier a retrouvé 6 scénarios, 4 380 observations historiques, 140 prévisions, 28 besoins opérationnels, 80 lignes de manifeste et les 28 allocations de chacune des 6 expériences.

Les doublons locaux S3 et S4, les sorties d'allocation autonomes, les artefacts Greedy non référencés de S1/S5, les logs et les caches restent exclus. Le contrôle textuel des artefacts sélectionnés n'a pas détecté de courriel, clé, secret ni chemin personnel. Les identifiants de professionnels présents dans les CSV sont synthétiques. Depuis la version 2, chaque expérience contient les trois méthodes sur la même instance.

## Mise à jour — version 2 (25 novembre 2026)

Corrections rendant le prototype fonctionnel de bout en bout :

- **Chemins d'artefacts portables** : les `experiment.json` contenaient des chemins Windows (`results\\...`), illisibles par l'API sous Linux/macOS (test en échec). Chemins désormais relatifs en `/`, et l'API accepte aussi les anciens.
- **Hash d'instance indépendant de l'OS** : `to_csv` produisait `\r\n` sous Windows, donc un ID d'expérience différent selon le poste. Forcé à `\n`.
- **Plus d'écrasement des méthodes** : lancer une seule méthode depuis le dashboard supprimait les autres de l'expérience. Les résultats sont désormais fusionnés.
- **Comparaison complète** : les 6 scénarios ont été recalculés avec Greedy, MILP/CBC et CP-SAT (18 runs, 18/18 valides) ; `results/experiments/scenario_summary.csv`.
- **Nouvelle vue « Comparaison scénarios »** (+ endpoint `/api/v1/dashboard/scenario-comparison`) : graphique groupé scénario × méthode sur 8 indicateurs, tableau avec écart vs S0, meilleure méthode par scénario.
- Lancement « Les 3 méthodes » par défaut depuis la vue Expériences ; `.gitignore` générique pour les expériences ; avertissements ESLint corrigés ; 3 tests de non-régression (`tests/test_portability.py`). 39/39 tests, ruff, typecheck, lint et `next build` OK.

## Mise à jour — correction des résultats (25 novembre 2026)

Un audit a montré que les premiers résultats de la version 2 étaient biaisés : MILP et CP-SAT (1 thread, 30 s, départ sur Greedy) rendaient les affectations de Greedy. Ils sont remplacés par ceux ci-dessous.

- **Solveurs** : CP-SAT sur 8 threads ; MILP/CBC sans warm start, avec borne et gap ; `OPTIMAL` seulement si la recherche est terminée. Budget configurable, commun aux deux : 50 s et 8 threads, soit ≈ 107 s par scénario (2 min maximum).
- **Occupation du jour 1** : MILP et CP-SAT enregistraient le besoin de fin de journée au lieu du recensement initial.
- **Validateur** : admissions acceptées ≤ demandées, et cohortes confrontées à l'instance. Il rejette bien les 12 anciens résultats exacts.
- **Chemins** : `method_result.json` ne contient plus de chemin absolu.
- **Dashboard** : minimum réel des admissions ; admissions entières lues dans l'instance (plafond de yhat).
- **Comparaison par graine** : une autre graine ne masque plus les méthodes de référence.

- **Commande `operational.requirements`** : l'empreinte ne porte plus que sur les paramètres de demande. Prévisions régénérées : valeurs identiques, instance S0 et identifiants d'expérience inchangés.
- **Modèle mathématique** : `docs/mathematical_model.md` décrit désormais les coefficients uniformes et les frontières réellement codés.

### Résultats (objectif canonique, plus bas = meilleur)

18 exécutions, 18 valides, aucune prouvée optimale. Meilleur objectif de chaque scénario en gras. Gap = (objectif − borne) / objectif.

| Scénario | Méthode | Objectif | vs Greedy | Gap | Refusées | Non soutenue | Couverture demande | Déficit RH | Équité | Temps |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| S0 nominal | Greedy | 636 379 | – | – | 4 | 18 | 99,0 % | 1 200 | 9 | 0,4 s |
| S0 nominal | MILP/CBC | 609 870 | -4,2 % | 2,7 % | 4 | 18 | 99,0 % | 1 147 | 0 | 52,9 s |
| S0 nominal | CP-SAT | **605 190** | -4,9 % | 2,8 % | 14 | 36 | 98,1 % | 1 102 | 0 | 52,3 s |
| S1 pic URG | Greedy | 695 559 | – | – | 29 | 68 | 96,5 % | 1 218 | 9 | 0,4 s |
| S1 pic URG | MILP/CBC | 666 041 | -4,2 % | 2,3 % | 30 | 69 | 96,4 % | 1 157 | 1 | 53,2 s |
| S1 pic URG | CP-SAT | **664 490** | -4,5 % | 2,8 % | 33 | 74 | 96,2 % | 1 144 | 0 | 52,0 s |
| S2 hausse +25 % | Greedy | 924 327 | – | – | 73 | 200 | 91,0 % | 1 408 | 7 | 0,4 s |
| S2 hausse +25 % | MILP/CBC | 903 320 | -2,3 % | 1,1 % | 73 | 200 | 91,0 % | 1 366 | 0 | 53,1 s |
| S2 hausse +25 % | CP-SAT | **899 240** | -2,7 % | 1,2 % | 76 | 208 | 90,7 % | 1 342 | 0 | 52,1 s |
| S3 absences 15 % | Greedy | 712 885 | – | – | 4 | 18 | 99,0 % | 1 353 | 15 | 0,4 s |
| S3 absences 15 % | MILP/CBC | 696 865 | -2,2 % | 2,2 % | 5 | 20 | 98,9 % | 1 317 | 15 | 52,6 s |
| S3 absences 15 % | CP-SAT | **690 635** | -3,1 % | 2,2 % | 19 | 43 | 97,7 % | 1 259 | 15 | 51,9 s |
| S4 crise combinée | Greedy | 1 002 335 | – | – | 73 | 200 | 91,0 % | 1 564 | 15 | 0,4 s |
| S4 crise combinée | MILP/CBC | **984 655** | -1,8 % | 0,2 % | 76 | 218 | 90,2 % | 1 493 | 15 | 52,8 s |
| S4 crise combinée | CP-SAT | 987 235 | -1,5 % | 1,1 % | 76 | 210 | 90,6 % | 1 514 | 15 | 51,9 s |
| S5 fermeture 10 % lits | Greedy | 674 469 | – | – | 26 | 109 | 94,1 % | 1 096 | 9 | 0,5 s |
| S5 fermeture 10 % lits | MILP/CBC | 650 444 | -3,6 % | 3,0 % | 27 | 111 | 94,0 % | 1 044 | 4 | 53,1 s |
| S5 fermeture 10 % lits | CP-SAT | **644 400** | -4,5 % | 3,3 % | 30 | 115 | 93,8 % | 1 024 | 0 | 52,1 s |

### Lecture

- Les solveurs exacts améliorent Greedy partout, de 1,5 à 4,9 %. CP-SAT est le meilleur sur S0, S1, S2, S3 et S5, MILP/CBC sur S4. Greedy reste utile : ≈ 0,4 s, au plus à 2,0–7,2 % de l'optimum.
- Le déficit RH représente 75 à 95 % de l'objectif, la demande non soutenue 2,5 à 23 %.
- Le gain vient surtout du personnel (S0 : 1 200 postes manquants avec Greedy, 1 147 avec MILP, 1 102 avec CP-SAT). Il se paie parfois en accueil : en S0, CP-SAT refuse 14 patients au lieu de 4 ; en S3, 19 au lieu de 4. Aucune méthode ne domine sur tous les KPI ; en S0 et S2, MILP fait mieux que Greedy à refus égaux.
- Couverture des postes cibles en S0 : 48 % (Greedy), 51 % (MILP), 52 % (CP-SAT). L'objectif ne pondère pas les services : en S0, MILP couvre URG à 30 % contre 48 % pour Greedy.
- En S3 et S4, l'équité vaut 15 pour les trois méthodes parce que les absents comptent avec une charge nulle.

### Pistes restantes pour le groupe
1. Enrichir la comparaison de stratégies : ajouter une stratégie naïve (ex. allocation proportionnelle sans priorité de service) et/ou des profils de pondération (« minimiser les coûts » vs « maximiser l'accueil »).
2. Volets normatif et réglementaire (loi 09-08, confidentialité, traçabilité) à documenter explicitement.
3. Mesurer un score d'utilisabilité (SUS) du dashboard auprès de quelques utilisateurs.
4. Compte rendu technique et répartition de la démo entre les 6 membres.

## Limites connues

- La frontière de l'horizon n'est pas contrôlée côté personnel (repos et nuits de la veille) ; voir `docs/mathematical_model.md`.
- Aucun artefact ne doit être interprété comme une donnée ou recommandation clinique réelle.
- Une méthode peut ne pas avoir produit d’artefact exploitable pour une expérience ; le dashboard affiche alors un état explicite, jamais un KPI inventé.
- Les solveurs exacts et la grille exhaustive de sensibilité sont coûteux et ne sont jamais lancés automatiquement.
- Les jobs sont suivis en mémoire par l’API ; leur état n’est pas conservé après un redémarrage, contrairement aux artefacts écrits.
- Playwright n'a été vérifié qu'avec Edge, et son test ne contrôle pas les données affichées.

## Avant publication ou phase suivante

1. Le dépôt sélectionne les données synthétiques, les prévisions, l'instance S0, six expériences S0–S5 et le manifeste de sensibilité pour la démonstration. Les autres sorties locales restent ignorées par Git.
2. Exécuter localement le build Next.js et Playwright.
3. Vérifier visuellement le dashboard avec FastAPI sur `127.0.0.1:8000` et Next.js sur `localhost:3011`.

Voir le [README](README.md) pour l’installation et les commandes, puis la documentation dans `docs/` pour le détail technique.
