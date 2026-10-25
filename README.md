# Suivi en simulation des six stratégies

**Simulation uniquement. La stratégie de production reste inchangée.**

Dernier passage : 2026-10-25T18:35:20.576919+00:00 — **review_required**.
Décisions figées avant match : 72. Résultats confirmés : 67.

Exécution sur GitHub après chaque pipeline de prévisions réussi et à 00:35, 06:35, 12:35 et 18:35 UTC chaque jour. Les horaires planifiés peuvent subir un retard GitHub.

| Portefeuille | Paris réglés | En attente | Mise en attente | Gain net (u) | ROI | Baisse max (u) | Gain des ajouts (u) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Production observée à la capture | 4 | 0 | 0.00 | 3.52 | 88.00 % | 1.00 | 0.00 |
| Référence + Bundesliga à demi-mise | 8 | 0 | 0.00 | 3.39 | 56.58 % | 0.50 | -0.12 |
| Référence + union des six, mise 1 | 34 | 2 | 2.00 | 3.22 | 9.47 % | 7.00 | -0.30 |
| Référence + union des six, mise 0,5 | 34 | 2 | 1.00 | 3.37 | 17.74 % | 3.50 | -0.15 |
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
| Serie A · extérieur outcome_control seule | 16 | 2 | 2.00 | 2.15 | 13.44 % | 3.55 | 2.15 |
| Référence + Serie A · extérieur outcome_control | 20 | 2 | 2.00 | 5.67 | 28.35 % | 2.30 | 2.15 |

La référence correspond aux recommandations de production observées lors de la première capture admissible, sur les mêmes matchs que les challengers. Elle ne reproduit donc pas tous les paris historiques de production.

Les six stratégies sont suivies seules, en ajout individuel, et en union à mise 1 ou 0,5. Les nuls Bundesliga ont aussi leur comparaison dédiée à demi-mise. Une union conserve en priorité le pari de référence, puis le premier membre admissible selon l’ordre figé : une seule mise par match.

Première capture complète entre 24 h et 5 min avant un horaire vérifié. Aucun remplissage a posteriori. Modèles, filtres et règles figés ; aucune promotion automatique. Les cotes Bet365 de Football-Data sont observées lors de la collecte, sans garantie de disponibilité réelle chez le bookmaker.

Le gain et le rendement concernent les paris réglés. La baisse maximale est calculée sur les gains réglés par jour de coup d’envoi UTC ; elle exclut les mises encore en attente. Zéro pari ne permet aucune conclusion sur la rentabilité.

[Exécutions GitHub](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-simulation.yml) · [Protocole](registration.json) · [Comparaison complète](comparison.csv) · [Diagnostics](last_run.json) · [Journal des preuves](evidence.json)

Journal : 284 événements, empreinte `d9b451533014683eded5c5177f099890d9d8c337ae9f41fa72a30b4a125c9560`.

Le journal et les captures sont conservés dans cette branche entre les exécutions. Une sauvegarde supplémentaire est jointe aux exécutions Actions pendant 90 jours. Un journal manquant ou altéré bloque le suivi.
