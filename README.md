# Suivi en simulation des six stratégies

**Simulation uniquement. La stratégie de production reste inchangée.**

Dernier passage : 2026-10-24T14:08:21.378442+00:00 — **collected**.
Décisions figées avant match : 63. Résultats confirmés : 41.

Exécution sur GitHub après chaque pipeline de prévisions réussi et à 00:35, 06:35, 12:35 et 18:35 UTC chaque jour. Les horaires planifiés peuvent subir un retard GitHub.

| Portefeuille | Paris réglés | En attente | Mise en attente | Gain net (u) | ROI | Baisse max (u) | Gain des ajouts (u) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Production observée à la capture | 2 | 2 | 2.00 | 2.27 | 113.50 % | 0.00 | 0.00 |
| Référence + Bundesliga à demi-mise | 5 | 3 | 2.50 | 0.77 | 22.00 % | 0.50 | -1.50 |
| Référence + union des six, mise 1 | 24 | 10 | 10.00 | -2.88 | -12.00 % | 7.00 | -5.15 |
| Référence + union des six, mise 0,5 | 24 | 10 | 6.00 | -0.31 | -2.35 % | 3.50 | -2.58 |
| Ligue 1 · domicile Poisson seule | 4 | 1 | 1.00 | -0.40 | -10.00 % | 1.00 | -0.40 |
| Référence + Ligue 1 · domicile Poisson | 6 | 3 | 3.00 | 1.87 | 31.17 % | 1.00 | -0.40 |
| Serie A · nul Poisson seule | 0 | 0 | 0.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Serie A · nul Poisson | 2 | 2 | 2.00 | 2.27 | 113.50 % | 0.00 | 0.00 |
| Serie A · nul logistique seule | 2 | 1 | 1.00 | -2.00 | -100.00 % | 2.00 | -2.00 |
| Référence + Serie A · nul logistique | 4 | 3 | 3.00 | 0.27 | 6.75 % | 1.00 | -2.00 |
| Bundesliga · nul XGBoost seule | 5 | 2 | 2.00 | -0.80 | -16.00 % | 1.00 | -0.80 |
| Référence + Bundesliga · nul XGBoost | 5 | 3 | 3.00 | -0.73 | -14.60 % | 1.00 | -3.00 |
| Premier League · extérieur logistique seule | 4 | 2 | 2.00 | -4.00 | -100.00 % | 4.00 | -4.00 |
| Référence + Premier League · extérieur logistique | 6 | 3 | 3.00 | -1.73 | -28.83 % | 3.00 | -4.00 |
| Serie A · extérieur outcome_control seule | 11 | 5 | 5.00 | 4.70 | 42.73 % | 2.38 | 4.70 |
| Référence + Serie A · extérieur outcome_control | 13 | 7 | 7.00 | 6.97 | 53.62 % | 1.00 | 4.70 |

La référence correspond aux recommandations de production observées lors de la première capture admissible, sur les mêmes matchs que les challengers. Elle ne reproduit donc pas tous les paris historiques de production.

Les six stratégies sont suivies seules, en ajout individuel, et en union à mise 1 ou 0,5. Les nuls Bundesliga ont aussi leur comparaison dédiée à demi-mise. Une union conserve en priorité le pari de référence, puis le premier membre admissible selon l’ordre figé : une seule mise par match.

Première capture complète entre 24 h et 5 min avant un horaire vérifié. Aucun remplissage a posteriori. Modèles, filtres et règles figés ; aucune promotion automatique. Les cotes Bet365 de Football-Data sont observées lors de la collecte, sans garantie de disponibilité réelle chez le bookmaker.

Le gain et le rendement concernent les paris réglés. La baisse maximale est calculée sur les gains réglés par jour de coup d’envoi UTC ; elle exclut les mises encore en attente. Zéro pari ne permet aucune conclusion sur la rentabilité.

[Exécutions GitHub](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-simulation.yml) · [Protocole](registration.json) · [Comparaison complète](comparison.csv) · [Diagnostics](last_run.json) · [Journal des preuves](evidence.json)

Journal : 229 événements, empreinte `30a55d7e8b5385fadd158e4387f6caa2b69ec49d47d6d37a2dee81e178771ae9`.

Le journal et les captures sont conservés dans cette branche entre les exécutions. Une sauvegarde supplémentaire est jointe aux exécutions Actions pendant 90 jours. Un journal manquant ou altéré bloque le suivi.
