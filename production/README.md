# ScorePredict Web

Cette couche sert les exports existants sans réentraîner le modèle à chaque visite. C'est le découplage important pour la production : le pipeline calcule et valide, puis le site lit un snapshot immuable.

## Démarrage local

```powershell
python -m production.server
```

Ouvrir `http://127.0.0.1:8000`. Le serveur de développement n'utilise que la bibliothèque standard Python.

En production, utiliser Gunicorn ou l'image Docker :

```powershell
docker build -t scorepredict-web .
docker run --rm -p 8000:8000 scorepredict-web
```

## Nouvelle saison 2026/27

Le wrapper live détecte maintenant automatiquement la saison commencée en juillet. En août 2026, `DataSeason` vaut donc `2026` et le modèle de production est entraîné jusqu'à la dernière saison terminée (`TrainMaxSeason 2025`). Les seuils de stratégie restent gelés.

Le portefeuille actif est `production_draw_consensus_nonfavorite_2026_08_12`. Il reprend exactement les quatre règles du champion multi-fold `draw_consensus_nonfavorite`. Son suivi prospectif commence le `2026-08-12`; les anciens portefeuilles et les simples tendances ne sont ni affichés, ni inclus dans son ROI live.

Publication complète :

```powershell
.\production\publish_dashboard.ps1 -DataSeason 2026 -TrainMaxSeason 2025 -BankrollEur 50
```

Ce flux exécute : collecte de la saison courante, enrichissement, reconstruction du dataset, audit, collecte des rencontres à venir, prédiction, journalisation et export du snapshot web.

## Mise à jour et publication avec GitHub

Le workflow `.github/workflows/daily-predictions.yml` planifie le calcul chaque jour à 00:35, 06:15, 12:15 et 18:35 dans le fuseau `Europe/Paris`, analyse les prochaines 24 heures, puis publie `production/static` sur GitHub Pages. Le passage après minuit couvre les rencontres du nouveau jour avant la collecte du matin ; celui du soir actualise aussi les rencontres qui viennent d'entrer dans la fenêtre. GitHub peut retarder les déclenchements planifiés : ces horaires ne constituent pas une garantie de publication à la minute. Le workflow peut aussi être lancé manuellement depuis l'onglet **Actions** du dépôt.

Les scripts `install_daily_task.ps1` et `run_daily_update.ps1` sont uniquement un mode de secours local. Ils ne doivent pas être activés sur un PC lorsque la publication GitHub Actions est utilisée, sinon la collecte est exécutée deux fois.

Le navigateur s'exécute sur une machine Windows temporaire fournie par GitHub : aucune fenêtre ne s'ouvre sur le PC de l'utilisateur. La collecte est tentée trois fois. Si le site de cotes bloque l'adresse du serveur GitHub, le workflow échoue et la dernière version valide de GitHub Pages reste en ligne. Des captures de diagnostic sont alors conservées pendant sept jours dans les fichiers du workflow.

Après avoir envoyé le workflow sur la branche principale, sélectionner **Settings → Pages → Source → GitHub Actions** une seule fois. Le premier lancement manuel permet de confirmer que le site de cotes accepte bien le serveur GitHub.

### Mémoire permanente des prévisions avec Supabase

La grande courbe de simulation historique n'est plus affichée aux utilisateurs. Le site montre uniquement les prévisions réellement publiées avant les matchs, puis leur état : en attente, gagnée, perdue ou annulée.

1. Créer un projet Supabase gratuit.
2. Exécuter `supabase/migrations/202608110001_prediction_history.sql`, puis
   `supabase/migrations/202608300001_fixture_registry.sql` dans l'éditeur SQL Supabase.
3. Dans **GitHub → Settings → Secrets and variables → Actions**, créer `SUPABASE_URL` et `SUPABASE_SECRET_KEY`.
4. Relancer le workflow **Prévisions quotidiennes et site**.

La clé secrète reste uniquement dans GitHub Actions et ne doit jamais être placée dans le JavaScript du site. Sans ces deux secrets, le suivi continue localement mais ne peut pas survivre à la suppression de la machine temporaire GitHub.

## Mise à jour quotidienne sous Windows

Le traitement peut être enregistré dans le Planificateur de tâches Windows. Il s'exécute chaque jour à 06:15, ignore un nouveau départ si un calcul est déjà en cours et écrit ses journaux dans `production/logs/`.

```powershell
.\production\install_daily_task.ps1
```

Le traitement quotidien collecte d'abord les calendriers des cinq championnats et vérifie les 96 clubs de la saison. Les clubs promus sont donc disponibles avant même leur premier match. Le site se relit ensuite automatiquement et n'affiche plus de bouton de rafraîchissement manuel.

Pour republier uniquement des exports déjà présents :

```powershell
python -m production.export_snapshot
```

L'export est refusé si un contrôle de qualité ou de fraîcheur n'est pas au vert. `--allow-stale` existe uniquement pour une prévisualisation ; l'interface affiche alors clairement l'alerte.

## API

- `GET /api/health` : disponibilité et état global.
- `GET /api/v1/dashboard` : read model complet (prédictions, KPI, courbes, risque, qualité, journal live).
- `GET /api/v1/dashboard?refresh=1` : invalide le cache mémoire et relit les exports.

Le service est en lecture seule. Les jobs longs et la collecte navigateur restent hors du processus web pour éviter les doubles calculs, les timeouts et les incohérences de publication.

## Déploiement statique

Le dossier `production/static/` est autonome. Sur un hébergeur statique, l'interface tente l'API puis se replie sur `data/dashboard.json`. Il suffit donc de régénérer le snapshot après chaque calcul et de déployer ce dossier.

### Option recommandée à 0 €

1. Calculer les prédictions sur un job séparé (machine locale ou GitHub Actions).
2. Écrire `production/static/data/dashboard.json` avec `python -m production.export_snapshot`.
3. Déployer `production/static` sur Cloudflare Pages.

Cloudflare Pages accepte 500 builds par mois sur le plan Free et le site reste disponible sans cold start. Les assets restent minuscules par rapport aux limites de fichiers. Documentation : [Cloudflare Pages limits](https://developers.cloudflare.com/pages/platform/limits/).

GitHub Actions peut orchestrer le calcul : les dépôts publics gardent les minutes gratuites ; GitHub Free fournit 2 000 minutes par mois aux dépôts privés. Documentation : [Actions limits](https://docs.github.com/en/actions/reference/limits) et [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

### Autres options gratuites

- **Render Static Site** : convient au même snapshot statique. Le site statique est gratuit.
- **Render Web Service** : exécute directement le Dockerfile et l'API Python, mais l'instance gratuite dort après 15 minutes, redémarre en environ une minute et son disque est éphémère. À réserver à une démo, pas au calcul planifié. [Limites Render Free](https://render.com/docs/free).
- **Hugging Face Static Space** : hébergement statique gratuit, pertinent pour une vitrine publique ML. Les nouveaux Spaces Docker/Gradio peuvent demander un plan payant et le calcul gratuit se met en veille. [Spaces overview](https://huggingface.co/docs/hub/spaces-overview).
- **GitHub Pages** : possible pour un projet public non commercial ; GitHub précise que Pages n'est pas destiné à héberger un SaaS commercial. [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits).
- **Supabase Free** : utile plus tard si le journal doit devenir multi-utilisateur (Postgres 500 Mo, 5 Go d'egress), mais inutile pour la première version en lecture seule. [Supabase pricing](https://supabase.com/pricing).

Vercel Hobby peut servir le front statique, mais ses fonctions ne sont pas adaptées à l'entraînement XGBoost ni au scraping navigateur : la durée maximale d'une fonction Hobby est configurable jusqu'à 60 secondes. [Vercel Hobby](https://vercel.com/docs/plans/hobby).

## Variables d'environnement

- `PORT` : port HTTP, `8000` par défaut.
- `HOST` : interface du serveur local, `127.0.0.1` par défaut.
- `SCOREPREDICT_ROOT` : racine contenant `train/output` et `inference/output` en mode dynamique.
- `SCOREPREDICT_DATA_TTL_SECONDS` : durée du cache mémoire, `30` secondes par défaut.

## Contrôles de publication

- saison courante présente ;
- audit de moins de 7 jours ;
- aucune cote d'ouverture manquante ;
- aucune valeur infinie dans les features ;
- export de prédictions de moins de 24 heures ;
- exclusion automatique des rencontres déjà commencées ;
- affichage séparé du backtest et du journal live ;
- probabilités brutes explicitement signalées comme non calibrées.


## Suivi personnel des neuf stratégies

Le suivi est local et absent du site client. Exécuter :

```powershell
python -m production.observation_personal --open
```

La page autonome est écrite dans `../suivi_prive_9/mon_suivi.html` et ne contacte
aucun service lors de sa consultation. Relancer la commande pour actualiser.
L'exporteur vérifie les journaux scellés et refuse toute sortie dans `production/static`.
Les workflows de publication ne génèrent pas ce suivi.

Les simulations historiques (`observation_history.json`, arrêtées au 17 octobre 2026)
restent séparées du suivi prospectif démarré le 18 octobre, heure de Paris.
Une seule issue et une unité virtuelle par match dans le total avec Bundesliga ;
les lignes individuelles ne s'additionnent pas.
La référence des journaux des neuf/quinze est `Bundesliga_anchor` (`native_mean`,
seuil 2 % après décote de prix). Elle diffère des deux règles du modèle public
scellé (minimum multiclasses/binaire, seuil commun 10 % et écart 4 points).
Le bilan de ce panier de recherche ne doit pas être présenté comme le bilan
de la version publique additionnée aux neuf. Le protocole figé reste inchangé.

Ce mode local ne rend pas privés les journaux techniques déjà présents dans le
repository GitHub public et son historique.

## Publication Bundesliga et observation Italie/Angleterre — 18 octobre 2026

La version de publication `bundesliga_only_2026_10_18` conserve les modèles et
filtres scellés du 5 septembre. Elle restreint les nouvelles recommandations
publiques aux deux règles de nul Bundesliga. L'identité du portefeuille de
modèles et son journal original ne sont pas renommés. Cette restriction a été
choisie après consultation des résultats 2026, sans nouvelle validation indépendante.

L'ancien pari Milan–Atalanta reste visible dans l'historique, marqué ancien pari
publié, et continue d'être réglé à sa cote d'origine. Il est exclu des cartes de
recommandations actuelles. Les bilans du site portent sur tous les paris déjà
publiés, anciennes versions comprises ; ils ne sont pas remis à zéro.

Les prochains signaux Serie A/EPL sont enregistrés avant match dans le portefeuille
Supabase distinct `observation_italy_epl_2026_10_18`. Les cotes originales et les
résultats terminaux restent immuables. Les montants EUR de ce suivi sont nuls ;
les gains sont exprimés en unités virtuelles. Les données en clair se trouvent
uniquement dans le dossier de travail `inference/output/private_observation`,
jamais dans `production/static`. Les artefacts Actions ne contiennent que le
rapport chiffré RSA-OAEP-SHA256 + AES-256-GCM. Les workflows ne possèdent que la
clé publique `production/observation_recipient.pem`.

La clé privée est conservée hors dépôt dans
`../suivi_prive_9/.private/observation_key.pem`. Ne pas la publier ni la supprimer :
elle est nécessaire pour lire les rapports archivés. La page personnelle la
charge localement via Node ; elle est indépendante des secrets Supabase.
`python -m production.observation_personal --open` actualise aussi ce suivi privé.

Le choix d'une stratégie à publier doit distinguer le suivi enregistré avant
match des simulations ayant servi à sa sélection. Au dernier journal des neuf
vérifié le 18 octobre à 11:42 UTC, aucun de leurs paris n'était encore réglé.

## Ajout public de l’extérieur Premier League — 18 octobre 2026

Sur demande explicite, `bundesliga_draw_epl_away_strict_2026_10_18` ajoute
`epl_away_logit_strict_2026_10_18` aux nuls Bundesliga existants. Les anciens
nuls EPL et Serie A restent privés. Le modèle sportif logistique scellé est
entraîné jusqu’à 2024 ; ses caractéristiques gardent la coupure sportive à J−3.
Les cotes B365 sont collectées sur Football-Data et rapprochées d’un horaire
Sportytrader UTC et d’une rencontre Understat non terminée. La sélection exige
une cote extérieure comprise entre 2 et 6 et `p_away * cote * 0.98 - 1 > 0.10`.
La collecte est horodatée ; elle ne certifie pas l’exécution chez le bookmaker.

`inference/english_away_worker.py` utilise les fonctions et modèles du dossier
scellé dans un processus séparé, après vérification de leurs empreintes et des
versions des bibliothèques. Il ne modifie aucun des anciens essais. Les sources,
caractéristiques, probabilités, exclusions et décisions sont conservées dans
`inference/output/english_public/` et dans les preuves du workflow quotidien.
Une erreur de collecte ou de modèle interrompt la publication ; un match hors
filtre produit une abstention. Aucun repli silencieux vers un autre modèle.

Le journal public d’origine conserve son identité et ses décisions déjà
publiées. Aucun pari de simulation n’est importé rétroactivement. Une seule mise
fixe de 1 unité est comptée par rencontre ; la valeur indicative de l’unité EUR
reste celle de la configuration, sans réduction automatique les jours chargés.
Les performances passées ont servi à choisir l’ajout anglais : le suivi public
qui commence maintenant doit être distingué de cette sélection exploratoire.

## Correctif du règlement Understat — 18 octobre 2026

Les deux workflows d’observation passent par
`python -m production.paper_settlement_runtime --experiment paper_simulation`
(ou `paper_positive15`). Cet adaptateur versionné ne modifie aucun fichier du
protocole scellé. Son empreinte, les protocoles sources acceptés et les fuseaux
IANA autorisés sont consignés dans `production/paper_settlement_runtime_v1.json`.

Pour chaque résultat, il vérifie l’empreinte de la capture Understat antérieure
au match et rapproche son heure de l’horaire UTC vérifié à cette époque. Il
établit ainsi si le champ sans fuseau était en UTC ou dans l’heure locale du
championnat. Seule la copie des données transmise au règlement est normalisée ;
les données brutes, les caractéristiques, les probabilités et les paris figés
restent inchangés. Les véritables déplacements de plus de 30 minutes, les
changements d’équipes, les révisions de score et les heures ambiguës restent
bloqués. Un ancrage manquant ou altéré ne permet jamais un règlement par défaut.

Chaque passage ajoute une trace `run` au journal existant et une capture
`settlement_runtime.json` avec l’empreinte du correctif et les conversions
appliquées. Les événements antérieurs restent dans la même chaîne. Le premier
cas corrigé est Lorient–Monaco : 15 h 15 à Paris = 13 h 15 UTC le 18 octobre,
comme dans les captures avant match. Aucun modèle n’est réentraîné.
