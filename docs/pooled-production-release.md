# Publication du filtre commun — version du 5 septembre 2026

Portefeuille : `production_draw_pooled_unweighted_2026_09_05`.

Cette version a été choisie explicitement par l'utilisateur après présentation de
ses limites. Elle est exploratoire, pas un rendement futur garanti.

## Contrat de la version 2026/27

- Quatre domaines de cote/championnat de la stratégie draw-consensus originale.
- Modèles non pondérés ; graine 42 ; entraînement unique jusqu'à la saison 2024.
- Filtre commun réglé exclusivement sur la saison 2025, selon la politique
  `pooled_cautious` : au moins 60 paris de validation, rendement positif et
  classement pénalisé par l'incertitude.
- Seuils obtenus : espérance estimée strictement supérieure à 0,10 et écart au
  marché supérieur ou égal à 0,04. Le minimum des deux modèles sert de signal.
- Modèles UBJ, colonnes d'entrée, filtres et empreintes dans
  `inference/releases/draw_pooled_2026_09_05/manifest.json`.
- Le traitement quotidien charge ces modèles ; il ne les réentraîne pas, même
  si le cache est absent. Un modèle modifié ou manquant bloque la publication.
- Les données 2026 fraîches alimentent les variables pré-match, jamais
  l'entraînement de cette version.
- Les mises restent inchangées : aucune augmentation liée au backtest.

## Historique et benchmark

Le +50,68 % sur 63 paris est la simulation 2025/26, avec entraînement jusqu'à
2023 et filtre réglé sur 2024. La version live utilise le même protocole décalé
d'une année. Les 60 paris et +27,92 % de 2025 utilisés pour son calibrage ne sont
pas un nouveau test indépendant et ne sont pas affichés comme du suivi réel.

Le résultat historique est sensible à l'entraînement : les mêmes anciens seuils
donnent environ +18 % avec trois graines moyennées. Il n'y avait aucun pari de
la politique commune sur les saisons 2019–2023. Ces limites restent archivées
avec le benchmark ; aucune prétention à une validation indépendante.

L'ancien portefeuille `production_draw_consensus_nonfavorite_2026_08_12` reste
identifiable et ses lignes Supabase ne sont ni supprimées ni réétiquetées.
Le suivi de la nouvelle version ne contient que ses propres décisions. Un
traitement de résultats continue de solder les paris de l'ancienne version,
mais exclut ceux-ci des statistiques de la nouvelle.
Un
moniteur ne peut pas mélanger le snapshot d'une version avec le journal d'une
autre ; il attend la première publication de la nouvelle version.

## Vérifications et retour arrière

`python -m inference.pooled_release` vérifie les fichiers et leur cohérence.
Les tests couvrent les seuils, les dates d'entraînement/calibrage, l'absence de
réentraînement implicite et la conservation de l'ancien historique.

Tout changement de modèles, de filtre ou de politique doit créer une nouvelle
version. Pour revenir à l'ancienne stratégie, restaurer ensemble sa configuration,
son benchmark et les deux workflows ; ne jamais renommer ses résultats sous la
nouvelle version. Ne pas effacer une version pour embellir le rendement.
