# Suivi séparé des 9 stratégies contre les 15

Les neuf stratégies sont celles positives sur les tests annuels 2025/26 et le
replay 2026/27 arrêté au 17 octobre 2026, avec leurs filtres actuels. Leur ordre
reste celui de l’inscription des quinze. Aucun modèle ni filtre n’est modifié.

[Rapport et paris](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/tree/observation-compare9-state)
· [Exécutions](https://github.com/Mohamed-Ali-SOBHI/ScorePredict/actions/workflows/paper-positive15.yml)

La comparaison utilise les prévisions et les prix déjà figés dans le journal des
quinze. Chaque match est inscrit dans un nouveau journal avant son coup d’envoi,
après l’inscription du protocole des neuf. Un match déjà commencé ou réglé ne
peut pas être ajouté. Les prévisions préexistantes encore admissibles sont
inscrites à l’heure actuelle, avec leur heure et leur prix source conservés.

Trois portefeuilles sont évalués sur cette même cohorte : Bundesliga seule,
Bundesliga + neuf, Bundesliga + quinze. Chaque portefeuille conserve une seule
issue et une seule unité virtuelle par match. Bundesliga est prioritaire, puis
l’ordre figé des membres. Les quinze peuvent retenir une autre issue que les
neuf si un membre exclu avait priorité ; cette divergence est conservée.

Les gains, rendements, mises, baisses maximales et différences sont calculés sur
les paris réglés. Les paris en attente sont séparés. Le suivi complet des quinze
garde son historique ; sa comparaison contre les neuf débute sur le nouveau
périmètre commun. Les anciennes simulations ne sont pas importées.

Le journal des neuf et ses rapports sont conservés sur la branche dédiée après
chaque passage réussi du suivi des quinze. Une empreinte du journal source et
une vérification de son préfixe empêchent de remplacer les anciennes décisions.
Une source ou un journal invalide bloque le suivi. Aucun redémarrage automatique.

Simulation uniquement, sans ordre de pari réel ni publication de nouvelles
recommandations sur le site. La sélection des neuf utilise des résultats déjà
connus : seuls les nouveaux matchs inscrits évaluent ce choix prospectivement.
