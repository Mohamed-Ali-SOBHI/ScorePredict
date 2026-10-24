# Suivi en simulation des six stratégies

**Simulation uniquement. La stratégie de production reste inchangée.**

Dernier passage : 2026-10-24T16:12:12.163855+00:00 — **collected**.
Décisions figées avant match : 63. Résultats confirmés : 50.

Exécution sur GitHub après chaque pipeline de prévisions réussi et à 00:35, 06:35, 12:35 et 18:35 UTC chaque jour. Les horaires planifiés peuvent subir un retard GitHub.

| Portefeuille | Paris réglés | En attente | Mise en attente | Gain net (u) | ROI | Baisse max (u) | Gain des ajouts (u) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Production observée à la capture | 2 | 2 | 2.00 | 2.27 | 113.50 % | 0.00 | 0.00 |
| Référence + Bundesliga à demi-mise | 6 | 2 | 2.00 | 2.14 | 53.62 % | 0.50 | -0.12 |
| Référence + union des six, mise 1 | 27 | 7 | 7.00 | 0.32 | 1.19 % | 7.00 | -1.95 |
| Référence + union des six, mise 0,5 | 27 | 7 | 4.50 | 1.29 | 8.93 % | 3.50 | -0.97 |
| Ligue 1 · domicile Poisson seule | 4 | 1 | 1.00 | -0.40 | -10.00 % | 1.00 | -0.40 |
| Référence + Ligue 1 · domicile Poisson | 6 | 3 | 3.00 | 1.87 | 31.17 % | 1.00 | -0.40 |
| Serie A · nul Poisson seule | 0 | 0 | 0.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Serie A · nul Poisson | 2 | 2 | 2.00 | 2.27 | 113.50 % | 0.00 | 0.00 |
| Serie A · nul logistique seule | 2 | 1 | 1.00 | -2.00 | -100.00 % | 2.00 | -2.00 |
| Référence + Serie A · nul logistique | 4 | 3 | 3.00 | 0.27 | 6.75 % | 1.00 | -2.00 |
| Bundesliga · nul XGBoost seule | 6 | 1 | 1.00 | 1.95 | 32.50 % | 1.00 | 1.95 |
| Référence + Bundesliga · nul XGBoost | 6 | 2 | 2.00 | 2.02 | 33.67 % | 1.00 | -0.25 |
| Premier League · extérieur logistique seule | 5 | 1 | 1.00 | -5.00 | -100.00 % | 5.00 | -5.00 |
| Référence + Premier League · extérieur logistique | 7 | 2 | 2.00 | -2.73 | -39.00 % | 4.00 | -5.00 |
| Serie A · extérieur outcome_control seule | 12 | 4 | 4.00 | 6.15 | 51.25 % | 2.38 | 6.15 |
| Référence + Serie A · extérieur outcome_control | 14 | 6 | 6.00 | 8.42 | 60.14 % | 1.00 | 6.15 |

La référence correspond aux recommandations de production observées lors de la première capture admissible, sur les mêmes matchs que les challengers. Elle ne reproduit donc pas tous les paris historiques de production.

Les six stratégies sont suivies seules, en ajout individuel, et en union à mise 1 ou 0,5. Les nuls Bundesliga ont aussi leur comparaison dédiée à demi-mise. Une union conserve en priorité le pari de référence, puis le premier membre admissible selon l’ordre figé : une seule mise par match.

Première capture complète entre 24 h et 5 min avant un horaire vérifié. Aucun remplissage a posteriori. Modèles, filtres et règles figés ; aucune promotion automatique. Les cotes Bet365 de Football-Data sont observées lors de la collecte, sans garantie de disponibilité réelle chez le bookmaker.

Le gain et le rendement concernent les paris réglés. La baisse maximale est calculée sur les gains réglés par jour de coup d’envoi UTC ; elle exclut les mises encore en attente. Zéro pari ne permet aucune conclusion sur la rentabilité.

[Exécutions GitHub](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-simulation.yml) · [Protocole](registration.json) · [Comparaison complète](comparison.csv) · [Diagnostics](last_run.json) · [Journal des preuves](evidence.json)

Journal : 240 événements, empreinte `277dbc48a3d70f73d115118a8249b39616c590f6bde2d7a864770fe3ea320cbc`.

Le journal et les captures sont conservés dans cette branche entre les exécutions. Une sauvegarde supplémentaire est jointe aux exécutions Actions pendant 90 jours. Un journal manquant ou altéré bloque le suivi.
