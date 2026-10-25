# Suivi en simulation des six stratégies

**Simulation uniquement. La stratégie de production reste inchangée.**

Dernier passage : 2026-10-25T09:55:45.786430+00:00 — **collected**.
Décisions figées avant match : 72. Résultats confirmés : 55.

Exécution sur GitHub après chaque pipeline de prévisions réussi et à 00:35, 06:35, 12:35 et 18:35 UTC chaque jour. Les horaires planifiés peuvent subir un retard GitHub.

| Portefeuille | Paris réglés | En attente | Mise en attente | Gain net (u) | ROI | Baisse max (u) | Gain des ajouts (u) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Production observée à la capture | 3 | 1 | 1.00 | 1.27 | 42.33 % | 1.00 | 0.00 |
| Référence + Bundesliga à demi-mise | 7 | 1 | 1.00 | 1.14 | 22.90 % | 0.50 | -0.12 |
| Référence + union des six, mise 1 | 30 | 6 | 6.00 | -0.23 | -0.77 % | 7.00 | -1.50 |
| Référence + union des six, mise 0,5 | 30 | 6 | 3.50 | 0.52 | 3.15 % | 3.50 | -0.75 |
| Ligue 1 · domicile Poisson seule | 5 | 0 | 0.00 | 1.05 | 21.00 % | 1.00 | 1.05 |
| Référence + Ligue 1 · domicile Poisson | 8 | 1 | 1.00 | 2.32 | 29.00 % | 1.00 | 1.05 |
| Serie A · nul Poisson seule | 0 | 0 | 0.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Serie A · nul Poisson | 3 | 1 | 1.00 | 1.27 | 42.33 % | 1.00 | 0.00 |
| Serie A · nul logistique seule | 2 | 1 | 1.00 | -2.00 | -100.00 % | 2.00 | -2.00 |
| Référence + Serie A · nul logistique | 5 | 2 | 2.00 | -0.73 | -14.60 % | 2.00 | -2.00 |
| Bundesliga · nul XGBoost seule | 7 | 0 | 0.00 | 0.95 | 13.57 % | 1.00 | 0.95 |
| Référence + Bundesliga · nul XGBoost | 7 | 1 | 1.00 | 1.02 | 14.57 % | 1.00 | -0.25 |
| Premier League · extérieur logistique seule | 5 | 1 | 1.00 | -5.00 | -100.00 % | 5.00 | -5.00 |
| Référence + Premier League · extérieur logistique | 8 | 1 | 1.00 | -3.73 | -46.63 % | 5.00 | -5.00 |
| Serie A · extérieur outcome_control seule | 13 | 5 | 5.00 | 5.15 | 39.62 % | 2.38 | 5.15 |
| Référence + Serie A · extérieur outcome_control | 16 | 6 | 6.00 | 6.42 | 40.12 % | 1.55 | 5.15 |

La référence correspond aux recommandations de production observées lors de la première capture admissible, sur les mêmes matchs que les challengers. Elle ne reproduit donc pas tous les paris historiques de production.

Les six stratégies sont suivies seules, en ajout individuel, et en union à mise 1 ou 0,5. Les nuls Bundesliga ont aussi leur comparaison dédiée à demi-mise. Une union conserve en priorité le pari de référence, puis le premier membre admissible selon l’ordre figé : une seule mise par match.

Première capture complète entre 24 h et 5 min avant un horaire vérifié. Aucun remplissage a posteriori. Modèles, filtres et règles figés ; aucune promotion automatique. Les cotes Bet365 de Football-Data sont observées lors de la collecte, sans garantie de disponibilité réelle chez le bookmaker.

Le gain et le rendement concernent les paris réglés. La baisse maximale est calculée sur les gains réglés par jour de coup d’envoi UTC ; elle exclut les mises encore en attente. Zéro pari ne permet aucune conclusion sur la rentabilité.

[Exécutions GitHub](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-simulation.yml) · [Protocole](registration.json) · [Comparaison complète](comparison.csv) · [Diagnostics](last_run.json) · [Journal des preuves](evidence.json)

Journal : 264 événements, empreinte `83c78ea43e2c8be4d54544723019b13960c7ddb2ee9f3428fe49297ad8b1bdb7`.

Le journal et les captures sont conservés dans cette branche entre les exécutions. Une sauvegarde supplémentaire est jointe aux exécutions Actions pendant 90 jours. Un journal manquant ou altéré bloque le suivi.
