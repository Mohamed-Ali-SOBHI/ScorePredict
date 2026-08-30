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

Le workflow `.github/workflows/daily-predictions.yml` lance le calcul chaque jour à 06:15 dans le fuseau `Europe/Paris`, analyse les 21 prochains jours, puis publie `production/static` sur GitHub Pages. Cette fenêtre évite de conserver un ancien export lorsque le champion n'a aucun championnat actif pendant le week-end immédiat. Le workflow peut aussi être lancé manuellement depuis l'onglet **Actions** du dépôt.

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
