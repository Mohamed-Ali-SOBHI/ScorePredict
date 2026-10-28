# Suivi en simulation des six stratégies

**Simulation uniquement. La stratégie de production reste inchangée.**

Dernier passage : 2026-10-28T11:27:03.825978+00:00 — **collected**.
Décisions figées avant match : 80. Résultats confirmés : 74.

Exécution sur GitHub après chaque pipeline de prévisions réussi et à 00:35, 06:35, 12:35 et 18:35 UTC chaque jour. Les horaires planifiés peuvent subir un retard GitHub.

| Portefeuille | Paris réglés | En attente | Mise en attente | Gain net (u) | ROI | Baisse max (u) | Gain des ajouts (u) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Production observée à la capture | 4 | 0 | 0.00 | 3.52 | 88.00 % | 1.00 | 0.00 |
| Référence + Bundesliga à demi-mise | 8 | 0 | 0.00 | 3.39 | 56.58 % | 0.50 | -0.12 |
| Référence + union des six, mise 1 | 38 | 5 | 5.00 | 4.08 | 10.74 % | 7.00 | 0.56 |
| Référence + union des six, mise 0,5 | 38 | 5 | 2.50 | 3.80 | 18.10 % | 3.50 | 0.28 |
| Ligue 1 · domicile Poisson seule | 5 | 0 | 0.00 | 1.05 | 21.00 % | 1.00 | 1.05 |
| Référence + Ligue 1 · domicile Poisson | 9 | 0 | 0.00 | 4.57 | 50.78 % | 1.00 | 1.05 |
| Serie A · nul Poisson seule | 1 | 0 | 0.00 | -1.00 | -100.00 % | 1.00 | -1.00 |
| Référence + Serie A · nul Poisson | 5 | 0 | 0.00 | 2.52 | 50.40 % | 1.00 | -1.00 |
| Serie A · nul logistique seule | 4 | 0 | 0.00 | 0.20 | 5.00 % | 2.00 | 0.20 |
| Référence + Serie A · nul logistique | 8 | 0 | 0.00 | 3.72 | 46.50 % | 2.00 | 0.20 |
| Bundesliga · nul XGBoost seule | 7 | 0 | 0.00 | 0.95 | 13.57 % | 1.00 | 0.95 |
| Référence + Bundesliga · nul XGBoost | 8 | 0 | 0.00 | 3.27 | 40.87 % | 1.00 | -0.25 |
| Premier League · extérieur logistique seule | 6 | 0 | 0.00 | -2.75 | -45.83 % | 5.00 | -2.75 |
| Référence + Premier League · extérieur logistique | 9 | 0 | 0.00 | -1.48 | -16.44 % | 5.00 | -5.00 |
| Serie A · extérieur outcome_control seule | 19 | 5 | 5.00 | 4.01 | 21.11 % | 2.44 | 4.01 |
| Référence + Serie A · extérieur outcome_control | 23 | 5 | 5.00 | 7.53 | 32.74 % | 1.55 | 4.01 |

La référence correspond aux recommandations de production observées lors de la première capture admissible, sur les mêmes matchs que les challengers. Elle ne reproduit donc pas tous les paris historiques de production.

Les six stratégies sont suivies seules, en ajout individuel, et en union à mise 1 ou 0,5. Les nuls Bundesliga ont aussi leur comparaison dédiée à demi-mise. Une union conserve en priorité le pari de référence, puis le premier membre admissible selon l’ordre figé : une seule mise par match.

Première capture complète entre 24 h et 5 min avant un horaire vérifié. Aucun remplissage a posteriori. Modèles, filtres et règles figés ; aucune promotion automatique. Les cotes Bet365 de Football-Data sont observées lors de la collecte, sans garantie de disponibilité réelle chez le bookmaker.

Le gain et le rendement concernent les paris réglés. La baisse maximale est calculée sur les gains réglés par jour de coup d’envoi UTC ; elle exclut les mises encore en attente. Zéro pari ne permet aucune conclusion sur la rentabilité.

[Exécutions GitHub](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-simulation.yml) · [Protocole](registration.json) · [Comparaison complète](comparison.csv) · [Diagnostics](last_run.json) · [Journal des preuves](evidence.json)

Journal : 341 événements, empreinte `d390f9ba3fd0eab91390f7a697a5ab70b31ed794ee775fba1b9d1a24de128044`.

Le journal et les captures sont conservés dans cette branche entre les exécutions. Une sauvegarde supplémentaire est jointe aux exécutions Actions pendant 90 jours. Un journal manquant ou altéré bloque le suivi.
