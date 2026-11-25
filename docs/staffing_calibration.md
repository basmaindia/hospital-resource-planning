# Pourquoi 48 % des postes cibles en S0 ? Diagnostic et recalibrage proposé

**Statut : proposition, non appliquée.** Les données, la configuration et les résultats publiés sont inchangés. Les effectifs et ratios sont des hypothèses synthétiques, pas des normes.

## Diagnostic (S0, plan Greedy : 48,3 %)

| Cause | Mesure | Effet |
|---|---|---|
| 1. Effectif environ deux fois trop petit | 2 322 postes cibles par semaine ; 235 agents × 5 postes = 1 175 | Plafond de **50,6 %** pour toute méthode à lits ouverts constants ; il faudrait 464 agents pour 100 % |
| 2. Qualifications déséquilibrées | MED : 37 % de la cible, 26 % des agents qualifiés. REA : 18 % de la cible, 50 % des agents. CHI : 20 % et 50 % | MED à 20 %, REA à 90 % ; même avec 464 agents, Greedy plafonne à 79,5 % |
| 3. Même cible jour et nuit | 774 postes cibles le matin, le soir et la nuit | Cible de nuit aussi élevée que le matin |
| 4. Arrondi au-dessus par besoin | 2 204 postes sans arrondi, 2 322 avec | +5 % de cible |

Par rôle, les agents disponibles et nécessaires sont : médecins 50 pour 118, infirmiers 110 pour 228, aides-soignants 75 pour 118.

La cause 2 vient du générateur (`_generate_staff`) : le nombre de qualifications et le premier service dépendent de la même parité d'indice. Un agent sur deux n'a qu'une qualification, et toujours CHI ou REA ; les autres forment les paires MED+REA et URG+CHI. **Aucun agent n'est affecté uniquement à MED ou à URG**, ce qui crée aussi les deux viviers disjoints {URG, CHI} et {REA, MED}. C'est un effet involontaire, pas une hypothèse.

Les absences (3 % par poste) jouent peu : presque tous les agents peuvent faire leurs 5 postes.

## Options essayées

Essais en mémoire sur l'instance S0 actuelle, avec de nouvelles qualifications (service principal au prorata des lits, un agent sur deux polyvalent) et des disponibilités tirées avec la même probabilité. Le montage redonne bien les chiffres publiés pour l'effectif actuel (41 % et 48 %).

| Option | Agents | S0 Naïve | S0 Greedy | S0 CP-SAT | S3 Greedy / CP-SAT | S4 Greedy / CP-SAT |
|---|---:|---:|---:|---:|---:|---:|
| Actuel | 235 | 41 % | 48 % | 51 % | 42 % / – | 38 % / 40 % |
| Qualifications seules | 235 | 44 % | 50 % | – | 43 % / – | 39 % / – |
| Effectif seul | 464 | 81 % | 80 % | – | – | – |
| Effectif + qualifications | 417 | 78 % | 80 % | – | 72 % / – | 67 % / – |
| Effectif + qualifications | 441 | 82 % | 84 % | 97 % | 76 % / – | 71 % / – |
| **Effectif + qualifications (recommandé)** | **450** | **84 %** | **85 %** | **98 %** | **76 % / 83 %** | **71 % / 76 %** |
| Effectif + qualifications | 464 | 86 % | 86 % | 99,9 % (optimal prouvé) | 78 % / – | 74 % / 78 % |
| Effectif + qualifications | 487 | 89 % | 88 % | – | 81 % / – | 76 % / – |

CP-SAT a un budget de 50 s et 8 threads, comme dans les résultats publiés ; « – » : non essayé. « Actuel » vient des résultats publiés et des mêmes essais.

### Recommandation

**450 agents : 115 médecins, 220 infirmiers, 115 aides-soignants, avec des qualifications équilibrées.** S0 devient une situation normale (Greedy 85 %, CP-SAT 98 %), S3 et S4 restent de vraies crises, et les méthodes se distinguent nettement : en S0 le coût passe de 210 384 (Greedy) à 67 300 (CP-SAT). Il n'est pas possible que Greedy **et** CP-SAT soient tous deux entre 85 et 95 % : l'écart entre eux est de 13 points. Si la cible doit être tenue par CP-SAT, viser plutôt 410 à 420 agents (estimation : CP-SAT vers 90 %, Greedy vers 80 %).

### Pourquoi pas les ratios seuls ?

Garder 235 agents imposerait environ 1 infirmier pour 10 lits et un demi-médecin et un demi-aide-soignant pour 10 lits (plafond 95 %), soit la moitié des cibles actuelles. Ce serait peu défendable et demanderait des ratios non entiers, que le modèle n'accepte pas. Différencier le soir et la nuit (cibles ×0,8 et ×0,6) est plus réaliste et ramène la cible à 1 881 postes, donc 365 agents au lieu de 450 pour le même plafond ; mais cela modifie le modèle (cible par poste dans Greedy, MILP, CP-SAT, validateur et besoins). C'est une extension possible, non simulée ici.

## Ce qu'impliquerait l'application

1. `configs/hospital.json` (effectifs) et `_generate_staff` (qualifications), avec tests.
2. Régénérer les données (≈ 11 s ; historique, occupation et lits restent identiques, vérifié) puis prévisions et instance S0 (≈ 40 s).
3. Passer le budget des solveurs de 50 à 45 s : avec deux fois plus d'agents, la construction des modèles s'allonge et un scénario atteint 120 s.
4. Recalculer les 72 résultats : **≈ 35 min**.
5. Recalculer la sensibilité Naïve + Greedy : ≈ 4 min ; sous-ensemble CP-SAT : ≈ 13 min.
6. Mettre à jour les documents et les tests qui citent des chiffres ou des identifiants : les identifiants S0–S5 changent.

Total de calcul : **≈ 55 min**, PC branché et sans veille. `staff_availability.csv` passerait de 25 à environ 50 Mo, à la limite de l'avertissement de GitHub (50 Mo) ; réduire l'historique conservé (seule la dernière semaine sert à la projection) éviterait le problème.

## Sous-ensemble CP-SAT proposé pour la sensibilité

14 cas, ≈ 54 s chacun, soit **≈ 13 min** :

- absences 0, 5, 10, 15, 20 % (demande ×1, 0 % de lits fermés) ;
- demande ×1,25, ×1,50, ×2 (absences 0 %) ;
- lits fermés 5 % et 10 % (demande ×1, absences 0 %) ;
- quatre crises combinées : absences 10 % et demande ×1,25 ; 20 % et ×1,25 ; 20 % et ×2 ; 15 %, ×1,25 et 10 % de lits fermés.

Les cas à 20 % de lits fermés sont exclus : aucun plan n'y respecte les contraintes. À lancer **après** la décision de recalibrage, pour ne pas calculer deux fois.
