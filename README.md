# Suivi en simulation des six stratégies

**Simulation uniquement. La stratégie de production reste inchangée.**

Dernier passage : 2026-10-26T17:28:25.805227+00:00 — **collected**.
Décisions figées avant match : 72. Résultats confirmés : 71.

Exécution sur GitHub après chaque pipeline de prévisions réussi et à 00:35, 06:35, 12:35 et 18:35 UTC chaque jour. Les horaires planifiés peuvent subir un retard GitHub.

| Portefeuille | Paris réglés | En attente | Mise en attente | Gain net (u) | ROI | Baisse max (u) | Gain des ajouts (u) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Production observée à la capture | 4 | 0 | 0.00 | 3.52 | 88.00 % | 1.00 | 0.00 |
| Référence + Bundesliga à demi-mise | 8 | 0 | 0.00 | 3.39 | 56.58 % | 0.50 | -0.12 |
| Référence + union des six, mise 1 | 36 | 0 | 0.00 | 4.33 | 12.03 % | 7.00 | 0.81 |
| Référence + union des six, mise 0,5 | 36 | 0 | 0.00 | 3.93 | 19.62 % | 3.50 | 0.41 |
| Ligue 1 · domicile Poisson seule | 5 | 0 | 0.00 | 1.05 | 21.00 % | 1.00 | 1.05 |
| Référence + Ligue 1 · domicile Poisson | 9 | 0 | 0.00 | 4.57 | 50.78 % | 1.00 | 1.05 |
| Serie A · nul Poisson seule | 0 | 0 | 0.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Serie A · nul Poisson | 4 | 0 | 0.00 | 3.52 | 88.00 % | 1.00 | 0.00 |
| Serie A · nul logistique seule | 3 | 0 | 0.00 | 1.20 | 40.00 % | 2.00 | 1.20 |
| Référence + Serie A · nul logistique | 7 | 0 | 0.00 | 4.72 | 67.43 % | 2.00 | 1.20 |
| Bundesliga · nul XGBoost seule | 7 | 0 | 0.00 | 0.95 | 13.57 % | 1.00 | 0.95 |
| Référence + Bundesliga · nul XGBoost | 8 | 0 | 0.00 | 3.27 | 40.87 % | 1.00 | -0.25 |
| Premier League · extérieur logistique seule | 6 | 0 | 0.00 | -2.75 | -45.83 % | 5.00 | -2.75 |
| Référence + Premier League · extérieur logistique | 9 | 0 | 0.00 | -1.48 | -16.44 % | 5.00 | -5.00 |
| Serie A · extérieur outcome_control seule | 18 | 0 | 0.00 | 3.26 | 18.11 % | 2.44 | 3.26 |
| Référence + Serie A · extérieur outcome_control | 22 | 0 | 0.00 | 6.78 | 30.82 % | 1.55 | 3.26 |

La référence correspond aux recommandations de production observées lors de la première capture admissible, sur les mêmes matchs que les challengers. Elle ne reproduit donc pas tous les paris historiques de production.

Les six stratégies sont suivies seules, en ajout individuel, et en union à mise 1 ou 0,5. Les nuls Bundesliga ont aussi leur comparaison dédiée à demi-mise. Une union conserve en priorité le pari de référence, puis le premier membre admissible selon l’ordre figé : une seule mise par match.

Première capture complète entre 24 h et 5 min avant un horaire vérifié. Aucun remplissage a posteriori. Modèles, filtres et règles figés ; aucune promotion automatique. Les cotes Bet365 de Football-Data sont observées lors de la collecte, sans garantie de disponibilité réelle chez le bookmaker.

Le gain et le rendement concernent les paris réglés. La baisse maximale est calculée sur les gains réglés par jour de coup d’envoi UTC ; elle exclut les mises encore en attente. Zéro pari ne permet aucune conclusion sur la rentabilité.

[Exécutions GitHub](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-simulation.yml) · [Protocole](registration.json) · [Comparaison complète](comparison.csv) · [Diagnostics](last_run.json) · [Journal des preuves](evidence.json)

Journal : 306 événements, empreinte `ee571abe1b3aa48462752a59e3f411291c82b49d9e1dd2aad954ac73fc3eef26`.

Le journal et les captures sont conservés dans cette branche entre les exécutions. Une sauvegarde supplémentaire est jointe aux exécutions Actions pendant 90 jours. Un journal manquant ou altéré bloque le suivi.
