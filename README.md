# Suivi en simulation des six stratégies

**Simulation uniquement. La stratégie de production reste inchangée.**

Dernier passage : 2026-11-01T02:37:12.777569+00:00 — **collected**.
Décisions figées avant match : 113. Résultats confirmés : 100.

Exécution sur GitHub après chaque pipeline de prévisions réussi et à 00:35, 06:35, 12:35 et 18:35 UTC chaque jour. Les horaires planifiés peuvent subir un retard GitHub.

| Portefeuille | Paris réglés | En attente | Mise en attente | Gain net (u) | ROI | Baisse max (u) | Gain des ajouts (u) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Production observée à la capture | 10 | 0 | 0.00 | -2.48 | -24.80 % | 6.00 | 0.00 |
| Référence + Bundesliga à demi-mise | 14 | 0 | 0.00 | -2.61 | -21.71 % | 6.00 | -0.12 |
| Référence + union des six, mise 1 | 55 | 5 | 5.00 | 0.26 | 0.47 % | 7.68 | 2.74 |
| Référence + union des six, mise 0,5 | 55 | 5 | 2.50 | -1.11 | -3.42 % | 6.84 | 1.37 |
| Ligue 1 · domicile Poisson seule | 6 | 0 | 0.00 | 2.80 | 46.67 % | 1.00 | 2.80 |
| Référence + Ligue 1 · domicile Poisson | 16 | 0 | 0.00 | 0.32 | 2.00 % | 6.00 | 2.80 |
| Serie A · nul Poisson seule | 1 | 1 | 1.00 | -1.00 | -100.00 % | 1.00 | -1.00 |
| Référence + Serie A · nul Poisson | 11 | 1 | 1.00 | -3.48 | -31.64 % | 7.00 | -1.00 |
| Serie A · nul logistique seule | 6 | 2 | 2.00 | -1.80 | -30.00 % | 3.00 | -1.80 |
| Référence + Serie A · nul logistique | 16 | 2 | 2.00 | -4.28 | -26.75 % | 9.00 | -1.80 |
| Bundesliga · nul XGBoost seule | 10 | 0 | 0.00 | -2.05 | -20.50 % | 3.00 | -2.05 |
| Référence + Bundesliga · nul XGBoost | 14 | 0 | 0.00 | -2.73 | -19.50 % | 6.00 | -0.25 |
| Premier League · extérieur logistique seule | 9 | 1 | 1.00 | -5.75 | -63.89 % | 5.75 | -5.75 |
| Référence + Premier League · extérieur logistique | 16 | 1 | 1.00 | -8.48 | -53.00 % | 9.75 | -6.00 |
| Serie A · extérieur outcome_control seule | 27 | 3 | 3.00 | 6.44 | 23.85 % | 2.44 | 6.44 |
| Référence + Serie A · extérieur outcome_control | 37 | 3 | 3.00 | 3.96 | 10.70 % | 7.43 | 6.44 |

La référence correspond aux recommandations de production observées lors de la première capture admissible, sur les mêmes matchs que les challengers. Elle ne reproduit donc pas tous les paris historiques de production.

Les six stratégies sont suivies seules, en ajout individuel, et en union à mise 1 ou 0,5. Les nuls Bundesliga ont aussi leur comparaison dédiée à demi-mise. Une union conserve en priorité le pari de référence, puis le premier membre admissible selon l’ordre figé : une seule mise par match.

Première capture complète entre 24 h et 5 min avant un horaire vérifié. Aucun remplissage a posteriori. Modèles, filtres et règles figés ; aucune promotion automatique. Les cotes Bet365 de Football-Data sont observées lors de la collecte, sans garantie de disponibilité réelle chez le bookmaker.

Le gain et le rendement concernent les paris réglés. La baisse maximale est calculée sur les gains réglés par jour de coup d’envoi UTC ; elle exclut les mises encore en attente. Zéro pari ne permet aucune conclusion sur la rentabilité.

[Exécutions GitHub](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-simulation.yml) · [Protocole](registration.json) · [Comparaison complète](comparison.csv) · [Diagnostics](last_run.json) · [Journal des preuves](evidence.json)

Journal : 452 événements, empreinte `9d5e43dfe4b2491549d37f9ef08bbafed0fce7cd20a6cfd3545d984da70f4f43`.

Le journal et les captures sont conservés dans cette branche entre les exécutions. Une sauvegarde supplémentaire est jointe aux exécutions Actions pendant 90 jours. Un journal manquant ou altéré bloque le suivi.
