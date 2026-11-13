# Suivi en simulation des six stratégies

**Simulation uniquement. La stratégie de production reste inchangée.**

Dernier passage : 2026-11-13T13:09:15.021455+00:00 — **collection_failed**.
Décisions figées avant match : 117. Résultats confirmés : 112.

Exécution sur GitHub après chaque pipeline de prévisions réussi et à 00:35, 06:35, 12:35 et 18:35 UTC chaque jour. Les horaires planifiés peuvent subir un retard GitHub.

| Portefeuille | Paris réglés | En attente | Mise en attente | Gain net (u) | ROI | Baisse max (u) | Gain des ajouts (u) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Production observée à la capture | 10 | 1 | 1.00 | -2.48 | -24.80 % | 6.00 | 0.00 |
| Référence + Bundesliga à demi-mise | 14 | 1 | 1.00 | -2.61 | -21.71 % | 6.00 | -0.12 |
| Référence + union des six, mise 1 | 60 | 4 | 4.00 | -2.34 | -3.90 % | 10.28 | 0.14 |
| Référence + union des six, mise 0,5 | 60 | 4 | 2.50 | -2.41 | -6.89 % | 8.14 | 0.07 |
| Ligue 1 · domicile Poisson seule | 6 | 1 | 1.00 | 2.80 | 46.67 % | 1.00 | 2.80 |
| Référence + Ligue 1 · domicile Poisson | 16 | 2 | 2.00 | 0.32 | 2.00 % | 6.00 | 2.80 |
| Serie A · nul Poisson seule | 2 | 0 | 0.00 | -2.00 | -100.00 % | 2.00 | -2.00 |
| Référence + Serie A · nul Poisson | 12 | 1 | 1.00 | -4.48 | -37.33 % | 8.00 | -2.00 |
| Serie A · nul logistique seule | 8 | 1 | 1.00 | -3.80 | -47.50 % | 5.00 | -3.80 |
| Référence + Serie A · nul logistique | 18 | 2 | 2.00 | -6.28 | -34.89 % | 11.00 | -3.80 |
| Bundesliga · nul XGBoost seule | 10 | 0 | 0.00 | -2.05 | -20.50 % | 3.00 | -2.05 |
| Référence + Bundesliga · nul XGBoost | 14 | 1 | 1.00 | -2.73 | -19.50 % | 6.00 | -0.25 |
| Premier League · extérieur logistique seule | 10 | 0 | 0.00 | -4.35 | -43.50 % | 5.75 | -4.35 |
| Référence + Premier League · extérieur logistique | 17 | 1 | 1.00 | -7.08 | -41.65 % | 9.75 | -4.60 |
| Serie A · extérieur outcome_control seule | 30 | 2 | 2.00 | 3.44 | 11.47 % | 4.43 | 3.44 |
| Référence + Serie A · extérieur outcome_control | 40 | 3 | 3.00 | 0.96 | 2.40 % | 10.43 | 3.44 |

La référence correspond aux recommandations de production observées lors de la première capture admissible, sur les mêmes matchs que les challengers. Elle ne reproduit donc pas tous les paris historiques de production.

Les six stratégies sont suivies seules, en ajout individuel, et en union à mise 1 ou 0,5. Les nuls Bundesliga ont aussi leur comparaison dédiée à demi-mise. Une union conserve en priorité le pari de référence, puis le premier membre admissible selon l’ordre figé : une seule mise par match.

Première capture complète entre 24 h et 5 min avant un horaire vérifié. Aucun remplissage a posteriori. Modèles, filtres et règles figés ; aucune promotion automatique. Les cotes Bet365 de Football-Data sont observées lors de la collecte, sans garantie de disponibilité réelle chez le bookmaker.

Le gain et le rendement concernent les paris réglés. La baisse maximale est calculée sur les gains réglés par jour de coup d’envoi UTC ; elle exclut les mises encore en attente. Zéro pari ne permet aucune conclusion sur la rentabilité.

[Exécutions GitHub](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-simulation.yml) · [Protocole](registration.json) · [Comparaison complète](comparison.csv) · [Diagnostics](last_run.json) · [Journal des preuves](evidence.json)

Journal : 478 événements, empreinte `71717ebe1deb58a746f3ae788762ec521187e97ab506e4eff74cacf3c9cb8170`.

Le journal et les captures sont conservés dans cette branche entre les exécutions. Une sauvegarde supplémentaire est jointe aux exécutions Actions pendant 90 jours. Un journal manquant ou altéré bloque le suivi.
