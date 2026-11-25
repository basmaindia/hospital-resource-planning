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
- Dashboard sur le port 3011 : dix vues, dont le simulateur, filtres, consultation des résultats et lancement manuel d’une méthode.

## Résultats et validations confirmés

- Les données et Greedy sont reproductibles pour une configuration et une graine identiques. MILP et CP-SAT, parallèles et limités en temps, peuvent varier légèrement d'une exécution à l'autre.
- La validation de prévision réserve le test final ; il n’intervient pas dans la sélection des modèles.
- Les trois méthodes utilisent les mêmes conventions d’unités et les mêmes composantes d’objectif.
- Les admissions refusées sont un KPI en patients ; la pénalité de demande est portée une seule fois par les journées-patients non soutenues.
- Contrôles confirmés le 25 novembre 2026 : `pytest -q` (95 tests), `ruff check src tests`, `npm.cmd run typecheck` et `npm.cmd run lint`. `npm.cmd run build` et Playwright (avec Edge) ont réussi lors de l'audit, avant ces corrections.

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

## Mise à jour — naïve, profils et équité (25 novembre 2026)

- **Stratégie naïve** : partage proportionnel sans priorité de service.
- **Trois profils de pondération** (`configs/profiles.json`), avec sélecteur dans la vue Comparaison scénarios.
- **Équité** : agents absents sur tout l'horizon exclus.
- **MILP** : reprise avec une autre graine si CBC s'arrête sur une assertion interne.

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

### Résultats par profil (plus bas = meilleur, au sein d'un profil)

72 exécutions, 72 respectant toutes les contraintes dures ; seul S3 « priorité accueil » est prouvé optimal. Meilleur objectif de chaque scénario en gras. Gap = (objectif − borne) / objectif.

#### Équilibré (`equilibre`)

| Scénario | Méthode | Objectif | vs Greedy | Gap | Refusées | Couverture demande | Déficit RH | Équité |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S0 nominal | Naïve | 718 885 | +13,0 % | – | 4 | 99,0 % | 1 365 | 15 |
| S0 nominal | Greedy | 636 379 | – | – | 4 | 99,0 % | 1 200 | 9 |
| S0 nominal | MILP/CBC | 609 870 | −4,2 % | 2,7 % | 4 | 99,0 % | 1 147 | 0 |
| S0 nominal | CP-SAT | **604 800** | −5,0 % | 2,8 % | 9 | 98,7 % | 1 123 | 0 |
| S1 pic URG | Naïve | 787 965 | +13,3 % | – | 31 | 95,9 % | 1 383 | 15 |
| S1 pic URG | Greedy | 695 559 | – | – | 29 | 96,5 % | 1 218 | 9 |
| S1 pic URG | MILP/CBC | 666 041 | −4,2 % | 2,3 % | 30 | 96,4 % | 1 157 | 1 |
| S1 pic URG | CP-SAT | **661 490** | −4,9 % | 2,3 % | 33 | 96,2 % | 1 138 | 0 |
| S2 hausse +25 % | Naïve | 1 010 265 | +9,3 % | – | 74 | 90,7 % | 1 566 | 15 |
| S2 hausse +25 % | Greedy | 924 327 | – | – | 73 | 91,0 % | 1 408 | 7 |
| S2 hausse +25 % | MILP/CBC | 903 320 | −2,3 % | 1,1 % | 73 | 91,0 % | 1 366 | 0 |
| S2 hausse +25 % | CP-SAT | **900 740** | −2,6 % | 1,5 % | 76 | 90,7 % | 1 345 | 0 |
| S3 absences 15 % | Naïve | 783 385 | +9,9 % | – | 4 | 99,0 % | 1 494 | 15 |
| S3 absences 15 % | Greedy | 712 876 | – | – | 4 | 99,0 % | 1 353 | 6 |
| S3 absences 15 % | MILP/CBC | 696 200 | −2,3 % | 2,4 % | 9 | 98,1 % | 1 286 | 0 |
| S3 absences 15 % | CP-SAT | **691 790** | −3,0 % | 2,2 % | 9 | 98,6 % | 1 295 | 0 |
| S4 crise combinée | Naïve | 1 083 265 | +8,1 % | – | 74 | 90,7 % | 1 712 | 15 |
| S4 crise combinée | Greedy | 1 002 325 | – | – | 73 | 91,0 % | 1 564 | 5 |
| S4 crise combinée | MILP/CBC | **988 260** | −1,4 % | 0,7 % | 73 | 90,8 % | 1 524 | 0 |
| S4 crise combinée | CP-SAT | 988 270 | −1,4 % | 1,2 % | 76 | 90,8 % | 1 526 | 0 |
| S5 fermeture 10 % lits | Naïve | 757 455 | +12,3 % | – | 27 | 94,0 % | 1 258 | 15 |
| S5 fermeture 10 % lits | Greedy | 674 469 | – | – | 26 | 94,1 % | 1 096 | 9 |
| S5 fermeture 10 % lits | MILP/CBC | 650 444 | −3,6 % | 3,0 % | 27 | 94,0 % | 1 044 | 4 |
| S5 fermeture 10 % lits | CP-SAT | **641 250** | −4,9 % | 2,7 % | 35 | 93,0 % | 988 | 0 |

#### Priorité accueil (`priorite_accueil`)

| Scénario | Méthode | Objectif | vs Greedy | Gap | Refusées | Couverture demande | Déficit RH | Équité |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S0 nominal | Naïve | 964 385 | +13,9 % | – | 4 | 99,0 % | 1 365 | 15 |
| S0 nominal | Greedy | 846 879 | – | – | 4 | 99,0 % | 1 200 | 9 |
| S0 nominal | MILP/CBC | **820 370** | −3,1 % | 0,0 % | 4 | 99,0 % | 1 147 | 0 |
| S0 nominal | CP-SAT | **820 370** | −3,1 % | 0,5 % | 4 | 99,0 % | 1 147 | 0 |
| S1 pic URG | Naïve | 1 847 465 | +9,3 % | – | 31 | 95,9 % | 1 383 | 15 |
| S1 pic URG | Greedy | 1 690 059 | – | – | 29 | 96,5 % | 1 218 | 9 |
| S1 pic URG | MILP/CBC | **1 657 550** | −1,9 % | 0,0 % | 29 | 96,5 % | 1 159 | 0 |
| S1 pic URG | CP-SAT | **1 657 550** | −1,9 % | 0,2 % | 29 | 96,5 % | 1 159 | 0 |
| S2 hausse +25 % | Naïve | 2 714 265 | +5,4 % | – | 74 | 90,7 % | 1 566 | 15 |
| S2 hausse +25 % | Greedy | 2 576 327 | – | – | 73 | 91,0 % | 1 408 | 7 |
| S2 hausse +25 % | MILP/CBC | **2 555 320** | −0,8 % | 0,0 % | 73 | 91,0 % | 1 366 | 0 |
| S2 hausse +25 % | CP-SAT | **2 555 320** | −0,8 % | 0,1 % | 73 | 91,0 % | 1 366 | 0 |
| S3 absences 15 % | Naïve | 1 040 885 | +10,0 % | – | 4 | 99,0 % | 1 494 | 15 |
| S3 absences 15 % | Greedy | 945 876 | – | – | 4 | 99,0 % | 1 353 | 6 |
| S3 absences 15 % | MILP/CBC | **930 370** | −1,6 % | 0,0 % | 4 | 99,0 % | 1 322 | 0 |
| S3 absences 15 % | CP-SAT | **930 370** | −1,6 % | 0,0 % | 4 | 99,0 % | 1 322 | 0 |
| S4 crise combinée | Naïve | 2 800 765 | +4,6 % | – | 74 | 90,7 % | 1 712 | 15 |
| S4 crise combinée | Greedy | 2 676 825 | – | – | 73 | 91,0 % | 1 564 | 5 |
| S4 crise combinée | MILP/CBC | **2 665 320** | −0,4 % | 0,0 % | 73 | 91,0 % | 1 541 | 0 |
| S4 crise combinée | CP-SAT | **2 665 320** | −0,4 % | 0,1 % | 73 | 91,0 % | 1 541 | 0 |
| S5 fermeture 10 % lits | Naïve | 1 402 455 | +11,3 % | – | 27 | 94,0 % | 1 258 | 15 |
| S5 fermeture 10 % lits | Greedy | 1 260 469 | – | – | 26 | 94,1 % | 1 096 | 9 |
| S5 fermeture 10 % lits | MILP/CBC | **1 233 460** | −2,1 % | 0,1 % | 26 | 94,1 % | 1 042 | 0 |
| S5 fermeture 10 % lits | CP-SAT | **1 233 460** | −2,1 % | 0,4 % | 26 | 94,1 % | 1 042 | 0 |

#### Priorité personnel (`priorite_personnel`)

| Scénario | Méthode | Objectif | vs Greedy | Gap | Refusées | Couverture demande | Déficit RH | Équité |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S0 nominal | Naïve | 1 061 620 | +13,3 % | – | 4 | 99,0 % | 1 365 | 15 |
| S0 nominal | Greedy | 937 270 | – | – | 4 | 99,0 % | 1 200 | 9 |
| S0 nominal | MILP/CBC | 999 970 | +6,7 % | 16,8 % | 169 | 76,1 % | 723 | 6 |
| S0 nominal | CP-SAT | **865 660** | −7,6 % | 4,4 % | 27 | 96,5 % | 1 045 | 0 |
| S1 pic URG | Naïve | 1 135 200 | +13,4 % | – | 31 | 95,9 % | 1 383 | 15 |
| S1 pic URG | Greedy | 1 000 950 | – | – | 29 | 96,5 % | 1 218 | 9 |
| S1 pic URG | MILP/CBC | 963 100 | −3,8 % | 6,8 % | 34 | 95,9 % | 1 155 | 4 |
| S1 pic URG | CP-SAT | **928 710** | −7,2 % | 3,9 % | 61 | 93,4 % | 1 045 | 0 |
| S2 hausse +25 % | Naïve | 1 403 250 | +9,9 % | – | 74 | 90,7 % | 1 566 | 15 |
| S2 hausse +25 % | Greedy | 1 277 020 | – | – | 73 | 91,0 % | 1 408 | 7 |
| S2 hausse +25 % | MILP/CBC | 1 237 200 | −3,1 % | 4,3 % | 81 | 90,3 % | 1 333 | 3 |
| S2 hausse +25 % | CP-SAT | **1 223 760** | −4,2 % | 3,5 % | 103 | 88,5 % | 1 264 | 0 |
| S3 absences 15 % | Naïve | 1 158 370 | +10,1 % | – | 4 | 99,0 % | 1 494 | 15 |
| S3 absences 15 % | Greedy | 1 051 720 | – | – | 4 | 99,0 % | 1 353 | 6 |
| S3 absences 15 % | MILP/CBC | 1 187 540 | +12,9 % | 19,2 % | 221 | 75,4 % | 955 | 3 |
| S3 absences 15 % | CP-SAT | **997 810** | −5,1 % | 4,3 % | 32 | 96,0 % | 1 208 | 0 |
| S4 crise combinée | Naïve | 1 512 750 | +8,5 % | – | 74 | 90,7 % | 1 712 | 15 |
| S4 crise combinée | Greedy | 1 393 820 | – | – | 73 | 91,0 % | 1 564 | 5 |
| S4 crise combinée | MILP/CBC | 1 361 520 | −2,3 % | 3,3 % | 126 | 81,9 % | 1 251 | 0 |
| S4 crise combinée | CP-SAT | **1 354 380** | −2,8 % | 3,2 % | 113 | 87,9 % | 1 421 | 0 |
| S5 fermeture 10 % lits | Naïve | 1 073 440 | +13,1 % | – | 27 | 94,0 % | 1 258 | 15 |
| S5 fermeture 10 % lits | Greedy | 949 360 | – | – | 26 | 94,1 % | 1 096 | 9 |
| S5 fermeture 10 % lits | MILP/CBC | 887 690 | −6,5 % | 5,5 % | 45 | 92,1 % | 966 | 1 |
| S5 fermeture 10 % lits | CP-SAT | **874 750** | −7,9 % | 4,5 % | 75 | 88,9 % | 871 | 0 |

### Lecture

- **CP-SAT est la méthode la plus régulière** : meilleure ou ex æquo sur 17 des 18 cas. En S4 équilibré, MILP le devance de 10 points sur 988 260, un écart négligeable.
- **Équilibré** : le meilleur solveur améliore Greedy de 1,4 à 5,0 %. CP-SAT refuse quelques patients de plus (9 au lieu de 4 en S0).
- **Priorité accueil** : MILP et CP-SAT trouvent le même objectif sur les six scénarios, à 0,1 % ou moins de la borne ; S3 est prouvé optimal par les deux. Les refus tombent au niveau de Greedy, qui accepte déjà tout ce que les lits permettent : ce sont les lits, pas les choix, qui imposent ces refus. Le gain vient du personnel (0,4 à 3,1 %).
- **Priorité personnel** : CP-SAT réduit le déficit RH de 9 à 21 % par rapport à Greedy, au prix de refus nettement plus nombreux (27 au lieu de 4 en S0, 113 au lieu de 73 en S4).
- **MILP n'est pas fiable avec priorité personnel** : en S0 et S3, il fait moins bien que Greedy (+6,7 % et +12,9 %), avec des gaps de 17 et 19 %. Sans solution initiale, 50 s ne lui suffisent pas.
- **Naïve** : toujours la moins bonne (4,6 à 13,9 % au-dessus de Greedy, sauf face à MILP en S3 priorité personnel). Le partage proportionnel laisse des postes vacants et une équité de 15, car il concentre la charge sur les premiers agents de la liste. Naïve et Greedy ont le même plan pour tous les profils.
- **Équité sans les absents** : en S3 et S4, Greedy passe de 15 à 6 et 5, et les solveurs atteignent 0 avec les profils équilibré et priorité accueil. La métrique redevient discriminante.
- **Qualifications** : URG et CHI d'un côté, REA et MED de l'autre, forment deux viviers disjoints. Donner la priorité à URG ne peut donc prendre du personnel qu'à CHI. En S0, MILP couvrait URG à 30 % avec équilibré ; avec priorité accueil il remonte à 48 %.
- Les objectifs de deux profils ne se comparent pas ; leurs KPI, oui.

### Conditions de calcul

Graine 42, 50 s et 8 threads par solveur exact, environ 106 s par scénario et par profil (32 min pour les 72 résultats). Naïve et Greedy prennent environ 1 s au plus. Le premier passage a été perturbé par la mise en veille du PC : les 9 expériences sur 18 qui chevauchaient une veille ont été relancées sans interruption, et le journal Windows vérifié. CBC a été relancé automatiquement avec la graine 43 sur S4 priorité personnel (assertion interne avec la graine 42). Empêcher la veille pendant un recalcul : les solveurs sont limités en temps réel.

### Pistes restantes pour le groupe
1. Ajouter CP-SAT sur un sous-ensemble de l'analyse de sensibilité (80 cas calculés en Naïve et Greedy).
2. Volets normatif et réglementaire (loi 09-08, confidentialité, traçabilité) à documenter explicitement.
3. Mesurer un score d'utilisabilité (SUS) du dashboard auprès de quelques utilisateurs.
4. Compte rendu technique et répartition de la démo entre les 6 membres.

## Limites connues

- La frontière de l'horizon n'est pas contrôlée côté personnel (repos et nuits de la veille) ; voir `docs/mathematical_model.md`.
- Aucun artefact ne doit être interprété comme une donnée ou recommandation clinique réelle.
- Une méthode peut ne pas avoir produit d’artefact exploitable pour une expérience ; le dashboard affiche alors un état explicite, jamais un KPI inventé.
- Les solveurs exacts et la grille exhaustive de sensibilité sont coûteux et ne sont jamais lancés automatiquement.
- Les jobs sont suivis en mémoire par l’API ; leur état n’est pas conservé après un redémarrage, contrairement aux artefacts écrits.
- Playwright n'a été vérifié qu'avec Edge (4 tests, dont le parcours du simulateur).

## Avant publication ou phase suivante

1. Le dépôt sélectionne les données synthétiques, les prévisions, l'instance S0, six expériences S0–S5 et le manifeste de sensibilité pour la démonstration. Les autres sorties locales restent ignorées par Git.
2. Exécuter localement le build Next.js et Playwright.
3. Vérifier visuellement le dashboard avec FastAPI sur `127.0.0.1:8000` et Next.js sur `localhost:3011`.

Voir le [README](README.md) pour l’installation et les commandes, puis la documentation dans `docs/` pour le détail technique.
