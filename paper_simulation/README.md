# Simulation prospective sur GitHub

Le workflow `paper-simulation.yml` exécute les six stratégies figées et compare
leurs paris supplémentaires à la production observée. Les nuls Bundesliga sont
également suivis à demi-mise. Aucun entraînement, pari réel ou changement de la
stratégie publiée n'est effectué.

[Consulter le rapport et l'historique persistant](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/tree/simulation-state)
ou [les exécutions](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-simulation.yml).

Le suivi tourne après chaque pipeline de prévisions réussi et quatre fois par
jour (00:35, 06:35, 12:35, 18:35 UTC). GitHub peut retarder les horaires planifiés.
Le journal SQLite, les captures compressées et les rapports sont conservés sur
la branche `simulation-state`. Les artefacts Actions servent de copie
supplémentaire pendant 90 jours. Aucun ordinateur personnel n'est nécessaire.

Les fichiers de `registration.json` sont vérifiés par SHA-256 avant chaque
passage. Les événements sont chaînés et les décisions déjà enregistrées ne
peuvent être réécrites. Une absence ou corruption du journal bloque la collecte.
Le workflow n'utilise aucun secret Supabase ni autorisation de publication Pages.
Son unique écriture distante est le journal sur la branche dédiée.

Les documents `migration/` conservent la provenance du démarrage local, qui ne
contenait aucune prédiction ni aucun résultat. La migration crée une nouvelle
inscription cloud avant les premières décisions ; elle conserve les modèles,
filtres, mises et règles de comparaison. Aucun résultat historique n'est ajouté.

Pour arrêter ce suivi, désactiver ce workflow dans GitHub Actions. Pour le
relancer manuellement, utiliser **Run workflow**. Tout changement de modèle,
de politique de production ou de saison exige une revue explicite du protocole.
Ne pas supprimer la branche d'état pour redémarrer : en cas d'échec de sauvegarde,
restaurer le dernier artefact et vérifier sa chaîne avant toute reprise.
