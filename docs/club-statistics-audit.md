# Contrôle des statistiques des clubs

Le pipeline GitHub `Previsions quotidiennes et site` contrôle la couverture de
la saison courante avant de calculer et publier les prédictions.

## Vérifications bloquantes

- Présence de 98 clubs uniques : Premier League 20, Liga 20, Bundesliga 18,
  Serie A 20, Ligue 1 18.
- Correspondance des identifiants et noms du registre avec les clubs ayant
  effectivement joué dans la source. Un historique supprimé par le filtrage
  des noms, comme auparavant pour Le Mans et le PSG, provoque une erreur.
- Correspondance exacte des dates et équipes entre calendrier des matchs
  terminés, historiques de la source et fichiers sauvegardés. Les doublons,
  adversaires incorrects et lignes perdues sont bloquants.
- Présence et conservation des buts, xG, npxG, xPoints, progressions profondes
  et composantes PPDA de chaque équipe et de son adversaire, ainsi que des
  résultats. Les buts et xG sont aussi comparés aux fiches des rencontres.
- Conservation des rencontres dans le même constructeur de données causales
  que celui utilisé en prédiction. Les dernières statistiques sportives ne
  peuvent pas être absentes lorsqu'une équipe a déjà joué cette saison.
- Sur les rencontres réellement à prédire, le nombre d'observations utilisées
  est comparé à l'historique antérieur au match. Le rapport recense aussi les
  valeurs absentes dans les colonnes des modèles figés.

Une erreur empêche le calcul ou la nouvelle publication. Elle ne remplace pas
les statistiques manquantes par des zéros. Le dernier site publié peut donc
rester visible avec son ancienne date de mise à jour.

## Preuves conservées sur GitHub

L'artefact `scorepredict-strategy-evidence-<run>-<attempt>` conserve 90 jours :

- `train/output/club_coverage_audit.json` : détail par club et championnat ;
- `train/output/club_coverage_sources/*.json` : réponses exactes utilisées par
  la collecte, avec date de capture et empreinte SHA-256 dans le rapport ;
- `inference/output/upcoming_input_audit.json` : contrôle des entrées des
  matchs à venir lorsqu'il y a des rencontres à prédire ;
- les rapports existants de qualité des données et de registre des clubs.

Le contrôle s'exécute dans les publications déjà planifiées sur GitHub. Il ne
nécessite aucun programme permanent sur l'ordinateur.

## Bilan du 16 octobre 2026

| Championnat | Clubs | Matchs terminés | Lignes d'équipes |
| --- | ---: | ---: | ---: |
| Premier League | 20 | 60 | 120 |
| Liga | 20 | 78 | 156 |
| Bundesliga | 18 | 45 | 90 |
| Serie A | 20 | 60 | 120 |
| Ligue 1 | 18 | 54 | 108 |
| **Total** | **98** | **297** | **594** |

Le contrôle des réponses de la source, de leur extraction et de la
reconstruction causale ne trouve pas d'autre historique courant perdu après
les corrections des alias Le Mans / Le Mans FC et Paris Saint Germain / PSG.
Le contrôle des 43 176 lignes sauvegardées des saisons antérieures à 2026 ne
trouve pas de valeur sportive essentielle absente, négative ou non finie dans
les 13 champs examinés. Ce dernier contrôle porte sur les lignes présentes ;
il ne reconstitue pas indépendamment les calendriers de toutes ces saisons.

Le premier passage complet sur GitHub a toutefois révélé des tirs et cotes
absents pour une rencontre : Rennes–PSG du 23 août 2026. La comparaison avec
les fichiers de marché archivés le 14 octobre révèle une inversion du domicile
dans Understat ; les 296 autres rencontres concordent sur les équipes, dates,
sens domicile/extérieur et scores. Les xG de fournisseurs différents ne sont
pas assimilés à des mesures identiques.

Le [compte rendu officiel du PSG](https://www.psg.fr/content/les-resultats-de-la-1re-journee-de-ligue-1-stade-rennais-paris-saint-journee-ligue-1-2026-2027)
et la [fiche officielle du match](https://www.psg.fr/matchs/football-masculin/20262027/paris-vs-rennes-2026-08-23)
confirment Rennes à domicile, au Roazhon Park, et le score de 2–2.
`verified_source_corrections.py` corrige uniquement cette rencontre identifiée
par son championnat, sa saison, son identifiant source, ses deux clubs et sa
date exacte. Chaque club conserve ses propres statistiques Understat ; le
domicile est rectifié avant la construction des variables et le rattachement
des tirs/cotes. Les tirs retrouvés sont 9 pour Rennes et 19 pour Paris.

La réponse originale reste conservée dans l'artefact. Le rapport liste la
correction et ses références. Si la source corrige elle-même le domicile,
la correction ne s'applique plus ; une identité/date inattendue bloque le
traitement. Il n'y a pas d'inversion automatique fondée sur les cotes.

Dans le premier audit des six rencontres à venir, les seules valeurs absentes
parmi les 127 variables des modèles sont six comparaisons avec la saison
précédente sur trois rencontres impliquant un promu : Le Mans, Frosinone et
Deportivo La Coruna. Leurs historiques courants contiennent respectivement
6, 6 et 8 matchs, tous transmis au modèle.

## Limites et absences normales

Les tirs et les cotes historiques proviennent d'une autre source. Leur absence
est comptée séparément dans le rapport ; elle ne signifie pas que les xG ou
l'historique des résultats ont disparu. Les cotes des prochains matchs sont
collectées séparément par le pipeline.

Une équipe promue peut ne pas avoir d'historique de la saison précédente dans
ce championnat. Les premières rencontres d'une saison peuvent aussi manquer
de certaines moyennes antérieures. Ces absences sont distinguées d'une perte
de matchs déjà joués ; aucune statistique de division inférieure n'est inventée.

Ces contrôles vérifient la cohérence et la transmission des données de la
source, pas leur vérité indépendante. Ils ne garantissent ni la calibration
du modèle ni la rentabilité des paris. Les modèles figés, filtres, mises et
stratégies de production ne sont pas modifiés par cet audit.
