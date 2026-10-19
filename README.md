# Suivi en simulation des six stratégies

**Simulation uniquement. La stratégie de production reste inchangée.**

Dernier passage : 2026-10-19T05:12:00.472984+00:00 — **collected**.
Décisions figées avant match : 36. Résultats confirmés : 33.

Exécution sur GitHub après chaque pipeline de prévisions réussi et à 00:35, 06:35, 12:35 et 18:35 UTC chaque jour. Les horaires planifiés peuvent subir un retard GitHub.

| Portefeuille | Paris réglés | En attente | Mise en attente | Gain net (u) | ROI | Baisse max (u) | Gain des ajouts (u) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Production observée à la capture | 2 | 0 | 0.00 | 2.27 | 113.50 % | 0.00 | 0.00 |
| Référence + Bundesliga à demi-mise | 4 | 0 | 0.00 | 1.27 | 42.33 % | 0.50 | -1.00 |
| Référence + union des six, mise 1 | 17 | 3 | 3.00 | 4.12 | 24.24 % | 4.11 | 1.85 |
| Référence + union des six, mise 0,5 | 17 | 3 | 1.50 | 3.19 | 33.63 % | 1.00 | 0.93 |
| Ligue 1 · domicile Poisson seule | 3 | 0 | 0.00 | 0.60 | 20.00 % | 1.00 | 0.60 |
| Référence + Ligue 1 · domicile Poisson | 5 | 0 | 0.00 | 2.87 | 57.40 % | 0.00 | 0.60 |
| Serie A · nul Poisson seule | 0 | 0 | 0.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Serie A · nul Poisson | 2 | 0 | 0.00 | 2.27 | 113.50 % | 0.00 | 0.00 |
| Serie A · nul logistique seule | 1 | 1 | 1.00 | -1.00 | -100.00 % | 1.00 | -1.00 |
| Référence + Serie A · nul logistique | 3 | 1 | 1.00 | 1.27 | 42.33 % | 1.00 | -1.00 |
| Bundesliga · nul XGBoost seule | 4 | 0 | 0.00 | 0.20 | 5.00 % | 1.00 | 0.20 |
| Référence + Bundesliga · nul XGBoost | 4 | 0 | 0.00 | 0.27 | 6.75 % | 1.00 | -2.00 |
| Premier League · extérieur logistique seule | 2 | 1 | 1.00 | -2.00 | -100.00 % | 2.00 | -2.00 |
| Référence + Premier League · extérieur logistique | 4 | 1 | 1.00 | 0.27 | 6.75 % | 1.00 | -2.00 |
| Serie A · extérieur outcome_control seule | 8 | 2 | 2.00 | 5.25 | 65.62 % | 2.38 | 5.25 |
| Référence + Serie A · extérieur outcome_control | 10 | 2 | 2.00 | 7.52 | 75.20 % | 1.00 | 5.25 |

La référence correspond aux recommandations de production observées lors de la première capture admissible, sur les mêmes matchs que les challengers. Elle ne reproduit donc pas tous les paris historiques de production.

Les six stratégies sont suivies seules, en ajout individuel, et en union à mise 1 ou 0,5. Les nuls Bundesliga ont aussi leur comparaison dédiée à demi-mise. Une union conserve en priorité le pari de référence, puis le premier membre admissible selon l’ordre figé : une seule mise par match.

Première capture complète entre 24 h et 5 min avant un horaire vérifié. Aucun remplissage a posteriori. Modèles, filtres et règles figés ; aucune promotion automatique. Les cotes Bet365 de Football-Data sont observées lors de la collecte, sans garantie de disponibilité réelle chez le bookmaker.

Le gain et le rendement concernent les paris réglés. La baisse maximale est calculée sur les gains réglés par jour de coup d’envoi UTC ; elle exclut les mises encore en attente. Zéro pari ne permet aucune conclusion sur la rentabilité.

[Exécutions GitHub](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-simulation.yml) · [Protocole](registration.json) · [Comparaison complète](comparison.csv) · [Diagnostics](last_run.json) · [Journal des preuves](evidence.json)

Journal : 112 événements, empreinte `52bda1f642bf45db75d08f388e444078ff3704d522bb71f7b3a517993a32af47`.

Le journal et les captures sont conservés dans cette branche entre les exécutions. Une sauvegarde supplémentaire est jointe aux exécutions Actions pendant 90 jours. Un journal manquant ou altéré bloque le suivi.
