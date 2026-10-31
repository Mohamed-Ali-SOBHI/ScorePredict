# Suivi en simulation des six stratégies

**Simulation uniquement. La stratégie de production reste inchangée.**

Dernier passage : 2026-10-31T20:45:32.453641+00:00 — **collected**.
Décisions figées avant match : 113. Résultats confirmés : 98.

Exécution sur GitHub après chaque pipeline de prévisions réussi et à 00:35, 06:35, 12:35 et 18:35 UTC chaque jour. Les horaires planifiés peuvent subir un retard GitHub.

| Portefeuille | Paris réglés | En attente | Mise en attente | Gain net (u) | ROI | Baisse max (u) | Gain des ajouts (u) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Production observée à la capture | 9 | 1 | 1.00 | -1.48 | -16.44 % | 5.00 | 0.00 |
| Référence + Bundesliga à demi-mise | 13 | 1 | 1.00 | -1.61 | -14.59 % | 5.00 | -0.12 |
| Référence + union des six, mise 1 | 54 | 6 | 6.00 | 1.26 | 2.33 % | 7.00 | 2.74 |
| Référence + union des six, mise 0,5 | 54 | 6 | 3.50 | -0.11 | -0.35 % | 5.84 | 1.37 |
| Ligue 1 · domicile Poisson seule | 6 | 0 | 0.00 | 2.80 | 46.67 % | 1.00 | 2.80 |
| Référence + Ligue 1 · domicile Poisson | 15 | 1 | 1.00 | 1.32 | 8.80 % | 5.00 | 2.80 |
| Serie A · nul Poisson seule | 1 | 1 | 1.00 | -1.00 | -100.00 % | 1.00 | -1.00 |
| Référence + Serie A · nul Poisson | 10 | 2 | 2.00 | -2.48 | -24.80 % | 6.00 | -1.00 |
| Serie A · nul logistique seule | 6 | 2 | 2.00 | -1.80 | -30.00 % | 3.00 | -1.80 |
| Référence + Serie A · nul logistique | 15 | 3 | 3.00 | -3.28 | -21.87 % | 8.00 | -1.80 |
| Bundesliga · nul XGBoost seule | 10 | 0 | 0.00 | -2.05 | -20.50 % | 3.00 | -2.05 |
| Référence + Bundesliga · nul XGBoost | 13 | 1 | 1.00 | -1.73 | -13.31 % | 5.00 | -0.25 |
| Premier League · extérieur logistique seule | 9 | 1 | 1.00 | -5.75 | -63.89 % | 5.75 | -5.75 |
| Référence + Premier League · extérieur logistique | 15 | 2 | 2.00 | -7.48 | -49.87 % | 8.75 | -6.00 |
| Serie A · extérieur outcome_control seule | 27 | 3 | 3.00 | 6.44 | 23.85 % | 2.44 | 6.44 |
| Référence + Serie A · extérieur outcome_control | 36 | 4 | 4.00 | 4.96 | 13.78 % | 6.43 | 6.44 |

La référence correspond aux recommandations de production observées lors de la première capture admissible, sur les mêmes matchs que les challengers. Elle ne reproduit donc pas tous les paris historiques de production.

Les six stratégies sont suivies seules, en ajout individuel, et en union à mise 1 ou 0,5. Les nuls Bundesliga ont aussi leur comparaison dédiée à demi-mise. Une union conserve en priorité le pari de référence, puis le premier membre admissible selon l’ordre figé : une seule mise par match.

Première capture complète entre 24 h et 5 min avant un horaire vérifié. Aucun remplissage a posteriori. Modèles, filtres et règles figés ; aucune promotion automatique. Les cotes Bet365 de Football-Data sont observées lors de la collecte, sans garantie de disponibilité réelle chez le bookmaker.

Le gain et le rendement concernent les paris réglés. La baisse maximale est calculée sur les gains réglés par jour de coup d’envoi UTC ; elle exclut les mises encore en attente. Zéro pari ne permet aucune conclusion sur la rentabilité.

[Exécutions GitHub](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-simulation.yml) · [Protocole](registration.json) · [Comparaison complète](comparison.csv) · [Diagnostics](last_run.json) · [Journal des preuves](evidence.json)

Journal : 446 événements, empreinte `a1dccdbf578a9aa3a561ced546682ba929c6216d51e31f2e670d8859cbea069f`.

Le journal et les captures sont conservés dans cette branche entre les exécutions. Une sauvegarde supplémentaire est jointe aux exécutions Actions pendant 90 jours. Un journal manquant ou altéré bloque le suivi.
