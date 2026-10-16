# Suivi en simulation des six stratégies

**Simulation uniquement. La stratégie de production reste inchangée.**

Dernier passage : 2026-10-16T16:54:03.034630+00:00 — **collected**.
Décisions figées avant match : 12. Résultats confirmés : 0.

Exécution sur GitHub après chaque pipeline de prévisions réussi et à 00:35, 06:35, 12:35 et 18:35 UTC chaque jour. Les horaires planifiés peuvent subir un retard GitHub.

| Portefeuille | Paris réglés | En attente | Mise en attente | Gain net (u) | ROI | Baisse max (u) | Gain des ajouts (u) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Production observée à la capture | 0 | 2 | 2.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Bundesliga à demi-mise | 0 | 4 | 3.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + union des six, mise 1 | 0 | 7 | 7.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + union des six, mise 0,5 | 0 | 7 | 4.50 | 0.00 | — | 0.00 | 0.00 |
| Ligue 1 · domicile Poisson seule | 0 | 0 | 0.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Ligue 1 · domicile Poisson | 0 | 2 | 2.00 | 0.00 | — | 0.00 | 0.00 |
| Serie A · nul Poisson seule | 0 | 0 | 0.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Serie A · nul Poisson | 0 | 2 | 2.00 | 0.00 | — | 0.00 | 0.00 |
| Serie A · nul logistique seule | 0 | 1 | 1.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Serie A · nul logistique | 0 | 3 | 3.00 | 0.00 | — | 0.00 | 0.00 |
| Bundesliga · nul XGBoost seule | 0 | 4 | 4.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Bundesliga · nul XGBoost | 0 | 4 | 4.00 | 0.00 | — | 0.00 | 0.00 |
| Premier League · extérieur logistique seule | 0 | 1 | 1.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Premier League · extérieur logistique | 0 | 3 | 3.00 | 0.00 | — | 0.00 | 0.00 |
| Serie A · extérieur outcome_control seule | 0 | 2 | 2.00 | 0.00 | — | 0.00 | 0.00 |
| Référence + Serie A · extérieur outcome_control | 0 | 4 | 4.00 | 0.00 | — | 0.00 | 0.00 |

La référence correspond aux recommandations de production observées lors de la première capture admissible, sur les mêmes matchs que les challengers. Elle ne reproduit donc pas tous les paris historiques de production.

Les six stratégies sont suivies seules, en ajout individuel, et en union à mise 1 ou 0,5. Les nuls Bundesliga ont aussi leur comparaison dédiée à demi-mise. Une union conserve en priorité le pari de référence, puis le premier membre admissible selon l’ordre figé : une seule mise par match.

Première capture complète entre 24 h et 5 min avant un horaire vérifié. Aucun remplissage a posteriori. Modèles, filtres et règles figés ; aucune promotion automatique. Les cotes Bet365 de Football-Data sont observées lors de la collecte, sans garantie de disponibilité réelle chez le bookmaker.

Le gain et le rendement concernent les paris réglés. La baisse maximale est calculée sur les gains réglés par jour de coup d’envoi UTC ; elle exclut les mises encore en attente. Zéro pari ne permet aucune conclusion sur la rentabilité.

[Exécutions GitHub](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-simulation.yml) · [Protocole](registration.json) · [Comparaison complète](comparison.csv) · [Diagnostics](last_run.json) · [Journal des preuves](evidence.json)

Journal : 27 événements, empreinte `0d262ef1c42b8e0826c2d34c3f76de3e7b8f1a2b3d1af714a5741f6f35c8c1bf`.

Le journal et les captures sont conservés dans cette branche entre les exécutions. Une sauvegarde supplémentaire est jointe aux exécutions Actions pendant 90 jours. Un journal manquant ou altéré bloque le suivi.
