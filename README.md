# Suivi en simulation des six stratégies

**Simulation uniquement. La stratégie de production reste inchangée.**

Dernier passage : 2026-10-17T13:49:56.368599+00:00 — **collected**.
Décisions figées avant match : 26. Résultats confirmés : 2.

Exécution sur GitHub après chaque pipeline de prévisions réussi et à 00:35, 06:35, 12:35 et 18:35 UTC chaque jour. Les horaires planifiés peuvent subir un retard GitHub.

| Portefeuille | Paris réglés | En attente | Mise en attente | Gain net (u) | ROI | Baisse max (u) | Gain des ajouts (u) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Production observée à la capture | 0 | 2 | 2.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Bundesliga à demi-mise | 1 | 3 | 2.50 | -0.50 | -100.00 % | 0.50 | -0.50 |
| Référence + union des six, mise 1 | 2 | 13 | 13.00 | -2.00 | -100.00 % | 2.00 | -2.00 |
| Référence + union des six, mise 0,5 | 2 | 13 | 7.50 | -1.00 | -100.00 % | 1.00 | -1.00 |
| Ligue 1 · domicile Poisson seule | 0 | 3 | 3.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Ligue 1 · domicile Poisson | 0 | 5 | 5.00 | 0.00 | — | 0.00 | 0.00 |
| Serie A · nul Poisson seule | 0 | 0 | 0.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Serie A · nul Poisson | 0 | 2 | 2.00 | 0.00 | — | 0.00 | 0.00 |
| Serie A · nul logistique seule | 1 | 0 | 0.00 | -1.00 | -100.00 % | 1.00 | -1.00 |
| Référence + Serie A · nul logistique | 1 | 2 | 2.00 | -1.00 | -100.00 % | 1.00 | -1.00 |
| Bundesliga · nul XGBoost seule | 1 | 3 | 3.00 | -1.00 | -100.00 % | 1.00 | -1.00 |
| Référence + Bundesliga · nul XGBoost | 1 | 3 | 3.00 | -1.00 | -100.00 % | 1.00 | -1.00 |
| Premier League · extérieur logistique seule | 0 | 2 | 2.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Premier League · extérieur logistique | 0 | 4 | 4.00 | 0.00 | — | 0.00 | 0.00 |
| Serie A · extérieur outcome_control seule | 1 | 5 | 5.00 | -1.00 | -100.00 % | 1.00 | -1.00 |
| Référence + Serie A · extérieur outcome_control | 1 | 7 | 7.00 | -1.00 | -100.00 % | 1.00 | -1.00 |

La référence correspond aux recommandations de production observées lors de la première capture admissible, sur les mêmes matchs que les challengers. Elle ne reproduit donc pas tous les paris historiques de production.

Les six stratégies sont suivies seules, en ajout individuel, et en union à mise 1 ou 0,5. Les nuls Bundesliga ont aussi leur comparaison dédiée à demi-mise. Une union conserve en priorité le pari de référence, puis le premier membre admissible selon l’ordre figé : une seule mise par match.

Première capture complète entre 24 h et 5 min avant un horaire vérifié. Aucun remplissage a posteriori. Modèles, filtres et règles figés ; aucune promotion automatique. Les cotes Bet365 de Football-Data sont observées lors de la collecte, sans garantie de disponibilité réelle chez le bookmaker.

Le gain et le rendement concernent les paris réglés. La baisse maximale est calculée sur les gains réglés par jour de coup d’envoi UTC ; elle exclut les mises encore en attente. Zéro pari ne permet aucune conclusion sur la rentabilité.

[Exécutions GitHub](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-simulation.yml) · [Protocole](registration.json) · [Comparaison complète](comparison.csv) · [Diagnostics](last_run.json) · [Journal des preuves](evidence.json)

Journal : 50 événements, empreinte `a34f414c61376c32c28e327a62f27529eefe38ec2f03f39424076ef425994fb0`.

Le journal et les captures sont conservés dans cette branche entre les exécutions. Une sauvegarde supplémentaire est jointe aux exécutions Actions pendant 90 jours. Un journal manquant ou altéré bloque le suivi.
