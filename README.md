# Suivi en simulation des six stratégies

**Simulation uniquement. La stratégie de production reste inchangée.**

Dernier passage : 2026-10-31T16:13:01.035359+00:00 — **collected**.
Décisions figées avant match : 106. Résultats confirmés : 84.

Exécution sur GitHub après chaque pipeline de prévisions réussi et à 00:35, 06:35, 12:35 et 18:35 UTC chaque jour. Les horaires planifiés peuvent subir un retard GitHub.

| Portefeuille | Paris réglés | En attente | Mise en attente | Gain net (u) | ROI | Baisse max (u) | Gain des ajouts (u) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Production observée à la capture | 5 | 5 | 5.00 | 2.52 | 50.40 % | 1.00 | 0.00 |
| Référence + Bundesliga à demi-mise | 9 | 5 | 5.00 | 2.39 | 34.21 % | 1.00 | -0.12 |
| Référence + union des six, mise 1 | 47 | 11 | 11.00 | 6.69 | 14.23 % | 7.00 | 4.17 |
| Référence + union des six, mise 0,5 | 47 | 11 | 8.00 | 4.61 | 17.71 % | 3.50 | 2.09 |
| Ligue 1 · domicile Poisson seule | 6 | 0 | 0.00 | 2.80 | 46.67 % | 1.00 | 2.80 |
| Référence + Ligue 1 · domicile Poisson | 11 | 5 | 5.00 | 5.32 | 48.36 % | 1.00 | 2.80 |
| Serie A · nul Poisson seule | 1 | 1 | 1.00 | -1.00 | -100.00 % | 1.00 | -1.00 |
| Référence + Serie A · nul Poisson | 6 | 6 | 6.00 | 1.52 | 25.33 % | 2.00 | -1.00 |
| Serie A · nul logistique seule | 5 | 3 | 3.00 | -0.80 | -16.00 % | 2.00 | -0.80 |
| Référence + Serie A · nul logistique | 10 | 8 | 8.00 | 1.72 | 17.20 % | 3.00 | -0.80 |
| Bundesliga · nul XGBoost seule | 7 | 3 | 3.00 | 0.95 | 13.57 % | 1.00 | 0.95 |
| Référence + Bundesliga · nul XGBoost | 9 | 5 | 5.00 | 2.27 | 25.22 % | 1.00 | -0.25 |
| Premier League · extérieur logistique seule | 7 | 2 | 2.00 | -3.75 | -53.57 % | 5.00 | -3.75 |
| Référence + Premier League · extérieur logistique | 10 | 6 | 6.00 | -2.48 | -24.80 % | 5.00 | -5.00 |
| Serie A · extérieur outcome_control seule | 26 | 3 | 3.00 | 5.87 | 22.58 % | 2.44 | 5.87 |
| Référence + Serie A · extérieur outcome_control | 31 | 8 | 8.00 | 8.39 | 27.06 % | 3.00 | 5.87 |

La référence correspond aux recommandations de production observées lors de la première capture admissible, sur les mêmes matchs que les challengers. Elle ne reproduit donc pas tous les paris historiques de production.

Les six stratégies sont suivies seules, en ajout individuel, et en union à mise 1 ou 0,5. Les nuls Bundesliga ont aussi leur comparaison dédiée à demi-mise. Une union conserve en priorité le pari de référence, puis le premier membre admissible selon l’ordre figé : une seule mise par match.

Première capture complète entre 24 h et 5 min avant un horaire vérifié. Aucun remplissage a posteriori. Modèles, filtres et règles figés ; aucune promotion automatique. Les cotes Bet365 de Football-Data sont observées lors de la collecte, sans garantie de disponibilité réelle chez le bookmaker.

Le gain et le rendement concernent les paris réglés. La baisse maximale est calculée sur les gains réglés par jour de coup d’envoi UTC ; elle exclut les mises encore en attente. Zéro pari ne permet aucune conclusion sur la rentabilité.

[Exécutions GitHub](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-simulation.yml) · [Protocole](registration.json) · [Comparaison complète](comparison.csv) · [Diagnostics](last_run.json) · [Journal des preuves](evidence.json)

Journal : 423 événements, empreinte `a8f5ad810c1d363a267dbf9aa5ab297a60019059df0539d600dd12bfc73515c5`.

Le journal et les captures sont conservés dans cette branche entre les exécutions. Une sauvegarde supplémentaire est jointe aux exécutions Actions pendant 90 jours. Un journal manquant ou altéré bloque le suivi.
