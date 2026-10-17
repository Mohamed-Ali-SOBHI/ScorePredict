# Nuls Bundesliga + 15 ajouts en observation

Suivi prospectif demandé le 17 octobre 2026. Les quinze ajouts sont exactement
les quinze contributions marginales positives du portefeuille élargi présenté
dans le rapport de recherche. Cette sélection utilise des résultats déjà connus ;
elle doit être évaluée sur de nouveaux matchs. Aucun ancien gain n'est importé.

[Rapport persistant et paris](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/tree/observation-positive15-state)
· [Exécutions](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-positive15.yml)

Une unité virtuelle par pari. Un seul pari par match dans le portefeuille commun,
y compris lorsque les stratégies choisissent des issues différentes : priorité
aux nuls Bundesliga puis à l'ordre figé de `members.json`. Les lignes individuelles
servent à comparer les stratégies et ne doivent pas être additionnées.
`tickets.json` et `tickets.csv` donnent chaque pari unique, sa cote, son origine,
toutes les stratégies qui ont sélectionné le match et son règlement.

Le comparateur Bundesliga reprend le modèle de recherche et ses trois graines,
avec les mêmes cotes et à la même capture que les ajouts. Ce n'est pas le journal
historique des recommandations publiées. Le suivi des six anciennes stratégies
continue séparément, avec son historique intact.

Les modèles sont copiés à l'identique depuis les études ; aucun entraînement
ni réajustement de filtre ne s'effectue pendant le suivi. Les prévisions et les
abstentions sont enregistrées à la première capture complète, entre 24 heures
et 5 minutes avant le coup d'envoi vérifié. Le journal ne permet ni réécriture,
ni remplissage après match. Les variables sportives restent calculées à J−3.
Les cotes Bet365 sont celles du fournisseur Football-Data lors de la collecte.

Le workflow tourne après un pipeline de prévisions réussi et à 00:40, 06:40,
12:40 et 18:40 UTC. GitHub peut retarder les horaires planifiés. Le journal,
les captures, les résultats et le rapport sont conservés sur la branche dédiée.
Un journal absent ou corrompu bloque le suivi ; il n'est jamais recréé automatiquement.

Simulation uniquement. Aucun ordre de pari, changement du site de production,
réentraînement ou promotion automatique.
