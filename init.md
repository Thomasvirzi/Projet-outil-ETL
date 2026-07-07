# Initialisation complète du projet depuis zéro

Ce document décrit l'ordre chronologique des commandes à lancer pour reconstruire l'environnement du projet ELT Commodities & Backtesting, en partant volontairement de `make infra-destroy`.

L'objectif est de repartir d'une infrastructure propre, recréer BigQuery avec Terraform, ingérer les données, exécuter les traitements NLP, construire les modèles dbt, puis ouvrir le dashboard Streamlit.

> Important : ce projet utilise BigQuery. Les commandes `infra-*`, `ingest`, `nlp`, `dbt-*` et `dashboard` supposent que l'authentification Google Cloud est correctement configurée sur la machine.

---

## 0. Se placer à la racine du projet

```bash
cd /Users/alexandremasson/Desktop/Ynov/Projet-outil-ETL
```

Ce dossier est la racine du repo. Toutes les commandes `make` du document doivent être lancées depuis cet emplacement, car le `Makefile` référence des chemins relatifs comme `scripts/`, `dbt_finance/` et `infrastructure/`.

---

## 1. Activer l'environnement Python

Si l'environnement virtuel existe déjà :

```bash
source .venv/bin/activate
```

S'il n'existe pas encore :

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

Ce que cela fait :

- crée ou active un environnement Python local au projet ;
- évite d'installer les dépendances dans le Python global de la machine ;
- garantit que les commandes Python du pipeline utilisent les librairies attendues par le repo.

Le `Makefile` détecte automatiquement `python` ou `python3` :

```makefile
PYTHON := $(shell command -v python 2>/dev/null || command -v python3)
```

Il est donc important d'activer le bon environnement avant de lancer les commandes `make`.

Le projet est prévu pour Python 3.12. Évite Python 3.14 pour le moment : `dbt` et certaines dépendances comme `mashumaro` peuvent échouer dès `make dbt-deps`.

Si `.venv` existe déjà mais a été créé avec Python 3.14, recrée-le :

```bash
deactivate
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
make install
```

---

## 2. Installer les dépendances Python

```bash
make install
```

Ce que cela fait :

```bash
python -m pip install -r requirements/requirements.txt
```

Cette étape installe notamment :

- `pandas`, `numpy` et les librairies de traitement de données ;
- `google-cloud-bigquery` pour écrire et lire dans BigQuery ;
- `dbt-bigquery` pour construire les modèles dbt ;
- `yfinance` pour récupérer les données de marché ;
- `feedparser` et `beautifulsoup4` pour les flux RSS ;
- les librairies NLP pour embeddings, sentiment et pertinence ;
- `streamlit` et `plotly` pour le dashboard.

Sans cette étape, les scripts peuvent échouer avec des erreurs du type :

```text
ModuleNotFoundError
google-cloud-bigquery is required
dbt: command not found
```

---

## 3. Configurer l'authentification Google Cloud

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project elt-commodities-backtesting
gcloud auth application-default set-quota-project elt-commodities-backtesting
```

Ce que cela fait :

- `gcloud auth login` connecte le CLI Google Cloud avec ton compte utilisateur ;
- `gcloud auth application-default login` crée des credentials locaux utilisables par Python, dbt et Terraform ;
- `gcloud config set project` définit le projet GCP actif ;
- `set-quota-project` associe les credentials ADC au projet, ce qui évite certains warnings ou erreurs de quota.

Le projet utilise volontairement l'authentification OAuth locale plutôt qu'une clé JSON de service account. C'est plus simple et plus sûr pour un usage local, surtout quand l'organisation GCP interdit la création de clés via la contrainte :

```text
constraints/iam.disableServiceAccountKeyCreation
```

Vérification rapide :

```bash
gcloud auth application-default print-access-token
```

Si cette commande retourne un token, les Application Default Credentials sont disponibles.

---

## 4. Préparer les variables d'environnement

Si `.env` n'existe pas encore :

```bash
cp .env.example .env
```

Puis vérifier que `.env` contient au minimum :

```bash
GOOGLE_CLOUD_PROJECT=elt-commodities-backtesting
BIGQUERY_LOCATION=EU
BIGQUERY_RAW_DATASET=raw
BIGQUERY_DBT_DATASET=dbt_finance
BIGQUERY_MART_DATASET=mart
BIGQUERY_MARTS_DATASET=mart
BIGQUERY_STAGING_DATASET=dbt_finance
BIGQUERY_MAX_BYTES_BILLED=1000000000
ENVIRONMENT=dev
DEFAULT_START_DATE=2020-01-01
PIPELINE_TIMEZONE=Europe/Paris
DEFAULT_INITIAL_CAPITAL=100000
DEFAULT_TRANSACTION_FEE_RATE=0.001
DEFAULT_SLIPPAGE_RATE=0.0005
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
NEWS_RELEVANCE_THRESHOLD=0.35
```

Charger les variables dans le terminal courant :

```bash
set -a
source .env
set +a
```

Ce que cela fait :

- rend les variables disponibles pour les commandes lancées ensuite ;
- permet à dbt de lire `GOOGLE_CLOUD_PROJECT` via `env_var` ;
- aligne Python, dbt, Streamlit et BigQuery sur les mêmes datasets.

Note importante :

- les scripts Python chargent généralement `.env` via `python-dotenv` ;
- dbt, lui, lit les variables d'environnement du terminal ;
- il est donc préférable de faire `source .env` avant `make dbt-run` ou `make dbt-build`.

---

## 5. Détruire l'infrastructure existante

```bash
make infra-destroy
```

Ce que cela lance :

```bash
terraform -chdir=infrastructure destroy -var-file=environments/dev.tfvars
```

Ce que Terraform essaie de supprimer :

- les datasets BigQuery gérés par Terraform ;
- le service account du pipeline ;
- les droits IAM associés ;
- le bucket Cloud Storage si `create_storage_bucket = true`.

Dans ce projet, les datasets BigQuery sont configurés avec :

```hcl
delete_contents_on_destroy = false
```

Cela signifie que Terraform ne supprimera pas silencieusement des datasets qui contiennent encore des tables. C'est une sécurité volontaire : elle évite d'effacer des données métier par accident.

Si `make infra-destroy` échoue avec une erreur comme :

```text
Dataset elt-commodities-backtesting:mart is still in use, resourceInUse
Dataset elt-commodities-backtesting:dbt_finance is still in use, resourceInUse
```

cela signifie que les datasets contiennent encore des tables, vues ou objets BigQuery. Terraform refuse donc de les supprimer, car `delete_contents_on_destroy = false`.

Deux options existent.

### Option A — recommandée pour continuer le projet

Ne pas chercher à détruire les datasets. Continuer simplement avec :

```bash
make infra-init
make infra-validate
make infra-plan
make infra-apply
```

Cette option est la meilleure si tu veux seulement t'assurer que l'infrastructure est bien conforme au code Terraform. `make infra-apply` ne dupliquera pas les datasets existants : Terraform va comparer l'existant avec le code et ne modifier que ce qui est nécessaire.

Dans ce cas, l'erreur `resourceInUse` n'est pas bloquante pour travailler. Elle indique seulement que la destruction complète est protégée.

### Option B — repartir d'une base BigQuery totalement vide

À utiliser seulement si tu acceptes de supprimer les données existantes du projet.

Lister d'abord le contenu des datasets :

```bash
bq ls --project_id=elt-commodities-backtesting raw
bq ls --project_id=elt-commodities-backtesting dbt_finance
bq ls --project_id=elt-commodities-backtesting mart
```

Si tu veux supprimer le contenu, le plus simple est de supprimer les datasets avec l'option récursive :

```bash
bq rm -r -f -d elt-commodities-backtesting:mart
bq rm -r -f -d elt-commodities-backtesting:dbt_finance
bq rm -r -f -d elt-commodities-backtesting:raw
```

Puis relancer :

```bash
make infra-destroy
make infra-apply
```

Ce que font les commandes `bq rm` :

- `-d` indique que l'on supprime un dataset ;
- `-r` supprime récursivement les tables et vues qu'il contient ;
- `-f` évite la confirmation interactive.

Cette option est destructive. Elle supprime les tables `raw`, `dbt_finance` et `mart`, donc il faudra ensuite relancer :

```bash
make dbt-ensure-raw
make ingest
make nlp
make dbt-build
```

pour reconstruire toute la donnée.

À ce stade, le but est de vérifier que tu sais revenir à un état propre. C'est une étape destructive, donc elle doit toujours être lancée consciemment.

---

## 6. Initialiser Terraform

```bash
make infra-init
```

Ce que cela lance :

```bash
terraform -chdir=infrastructure init
```

Ce que cela fait :

- initialise le dossier `infrastructure/` comme projet Terraform ;
- télécharge le provider Google ;
- crée ou met à jour `.terraform/` ;
- vérifie le lockfile `.terraform.lock.hcl`.

Cette commande ne crée aucune ressource dans GCP. Elle prépare seulement Terraform à exécuter les étapes suivantes.

---

## 7. Valider la configuration Terraform

```bash
make infra-validate
```

Ce que cela lance :

```bash
terraform -chdir=infrastructure validate
```

Ce que cela vérifie :

- la syntaxe des fichiers `.tf` ;
- la cohérence des variables ;
- la validité globale du graphe Terraform.

Cette commande ne contacte pas forcément toutes les APIs GCP et ne crée rien. Elle répond à la question : “est-ce que mon code Terraform est structurellement valide ?”

---

## 8. Prévisualiser le plan Terraform

```bash
make infra-plan
```

Ce que cela lance :

```bash
terraform -chdir=infrastructure plan -var-file=environments/dev.tfvars
```

Ce que cela fait :

- lit `infrastructure/environments/dev.tfvars` ;
- compare l'état Terraform local avec l'état réel dans GCP ;
- affiche les ressources à créer, modifier ou supprimer.

Les valeurs importantes du projet sont :

```hcl
project_id  = "elt-commodities-backtesting"
region      = "europe-west1"
location    = "EU"

raw_dataset_id  = "raw"
dbt_dataset_id  = "dbt_finance"
mart_dataset_id = "mart"

service_account_id = "etl-commodities-pipeline"
```

À vérifier dans le plan :

- les datasets BigQuery doivent être dans la localisation `EU` ;
- le projet doit être `elt-commodities-backtesting` ;
- Terraform ne doit pas annoncer de suppression inattendue ;
- le service account doit être celui du pipeline.

---

## 9. Appliquer l'infrastructure Terraform

```bash
make infra-apply
```

Ce que cela lance :

```bash
terraform -chdir=infrastructure apply -var-file=environments/dev.tfvars
```

Ce que cela crée ou remet en place :

```text
Google Cloud Project
├── APIs activées
│   ├── BigQuery API
│   ├── BigQuery Storage API
│   ├── IAM API
│   ├── Service Usage API
│   ├── Cloud Resource Manager API
│   └── Cloud Storage API
├── BigQuery
│   ├── raw
│   ├── dbt_finance
│   └── mart
├── IAM
│   └── etl-commodities-pipeline@...
└── Cloud Storage optionnel
```

Rôle des datasets :

- `raw` reçoit les données brutes ingérées par Python ;
- `dbt_finance` reçoit les modèles landing, staging et warehouse de dbt ;
- `mart` reçoit les tables finales utilisées par le backtesting et Streamlit.

Rôle IAM du service account :

- `roles/bigquery.jobUser` au niveau projet pour lancer des jobs BigQuery ;
- `roles/bigquery.dataEditor` sur les datasets pour créer et modifier les tables.

À la fin, Terraform affiche des outputs comme :

```text
project_id
bigquery_location
raw_dataset_id
dbt_dataset_id
mart_dataset_id
pipeline_service_account_email
```

---

## 10. Installer les dépendances dbt

```bash
make dbt-deps
```

Ce que cela lance :

```bash
cd dbt_finance && dbt deps --profiles-dir .
```

Ce que cela fait :

- lit `dbt_finance/packages.yml` ;
- installe les packages dbt nécessaires dans `dbt_finance/dbt_packages/`.

Cette étape est nécessaire avant certains modèles ou tests qui utilisent des macros externes.

---

## 11. Créer les tables raw si besoin

```bash
make dbt-ensure-raw
```

Ce que cela lance :

```bash
python scripts/extract_load/ensure_raw_tables.py
```

Ce que cela fait :

- vérifie l'existence des tables brutes dans `raw` ;
- crée les tables manquantes avec le schéma attendu ;
- prépare BigQuery pour recevoir les sorties des scripts d'ingestion et NLP.

Exemples de tables raw :

```text
raw.market_data_raw
raw.benchmarks_raw
raw.news_raw
raw.news_embeddings_raw
raw.news_sentiment_raw
raw.article_commodity_relevance_raw
raw.news_features_raw
raw.pipeline_logs_raw
```

Cette étape est idempotente : la relancer ne doit pas dupliquer la donnée métier. Elle sert à garantir que les tables existent.

---

## 12. Vérifier l'orchestration sans exécuter

```bash
python scripts/orchestrate.py --dry-run
```

Ce que cela fait :

- liste les tâches du pipeline dans l'ordre ;
- écrit un log d'exécution simulé ;
- ne lance pas réellement les scripts.

L'ordre logique du pipeline complet est :

```text
ingest_market
ingest_benchmarks
ingest_rss
create_embeddings
compute_sentiment
compute_relevance
compute_news_indicators
ensure_raw_tables
dbt_run
dbt_test
update_backtests
```

Cette commande est utile pour vérifier que l'environnement Python et les chemins du projet sont corrects avant de consommer du temps sur l'ingestion ou le NLP.

---

## 13. Lancer l'ingestion des données brutes

```bash
make ingest
```

Ce que cela lance :

```bash
python scripts/orchestrate.py --only ingest
```

Cette étape exécute trois familles d'ingestion.

### 13.1 Données marché commodities

Script :

```text
scripts/extract_load/ingest_commodities.py
```

Ce qu'il fait :

- lit les actifs définis dans `config/commodities.yml` ;
- conserve par défaut uniquement les actifs `enabled: true` ;
- récupère les prix OHLCV via Yahoo Finance ;
- applique des mécanismes de fallback local si Yahoo limite les requêtes ;
- écrit les données dans `raw.market_data_raw` ;
- écrit aussi des fichiers locaux de suivi dans `data/raw/market_data/`.

Dans la configuration actuelle, `config/commodities.yml` contient 20 actifs et ils sont tous activés. Le run standard tente donc de charger les 20 actifs, sauf si tu ajoutes un filtre comme `--priorities` ou `--symbols`.

Pour visualiser la sélection exacte sans appeler Yahoo Finance :

```bash
python scripts/extract_load/ingest_commodities.py --dry-run
```

Pour inclure aussi d'éventuels actifs désactivés si la configuration évolue plus tard :

```bash
python scripts/extract_load/ingest_commodities.py --dry-run --include-disabled
```

La table cible contient les prix par actif et par date. Elle sert ensuite de base aux indicateurs techniques et aux stratégies.

### 13.2 Données benchmark

Script :

```text
scripts/extract_load/ingest_benchmarks.py
```

Ce qu'il fait :

- lit la composition définie dans `config/benchmarks.yml` ;
- construit un benchmark commodities synthétique ;
- peut utiliser les données marché déjà ingérées comme fallback ;
- charge les résultats dans `raw.benchmarks_raw`.

Ce benchmark est ensuite transformé par dbt et exposé comme actif backtestable sous le symbole :

```text
COMMODITY_INDEX
```

### 13.3 Flux RSS

Script :

```text
scripts/extract_load/ingest_rss.py
```

Ce qu'il fait :

- lit les sources dans `config/rss_sources.yml` ;
- récupère les articles disponibles ;
- nettoie les titres, descriptions, dates et URLs ;
- déduplique les articles ;
- charge les données dans `raw.news_raw`.

Ces articles alimentent ensuite la partie NLP du pipeline.

---

## 14. Lancer les traitements NLP

```bash
make nlp
```

Ce que cela lance :

```bash
python scripts/orchestrate.py --only nlp
```

Cette étape transforme les articles RSS en signaux textuels exploitables par les stratégies.

### 14.1 Embeddings

Script :

```text
scripts/nlp/create_embeddings.py
```

Ce qu'il fait :

- lit les articles depuis `raw.news_raw` ;
- calcule une représentation vectorielle du texte ;
- écrit le résultat dans `raw.news_embeddings_raw`.

Les embeddings servent ensuite à rapprocher les articles des matières premières concernées.

### 14.2 Sentiment

Script :

```text
scripts/nlp/compute_sentiment.py
```

Ce qu'il fait :

- analyse le ton des articles ;
- produit un score de sentiment ;
- écrit les résultats dans `raw.news_sentiment_raw`.

Le score de sentiment permet de savoir si le flux d'actualité est plutôt positif, neutre ou négatif.

### 14.3 Pertinence article / commodity

Script :

```text
scripts/nlp/compute_relevance.py
```

Ce qu'il fait :

- compare les articles avec les commodities suivies ;
- estime quelles matières premières sont concernées ;
- écrit les correspondances dans `raw.article_commodity_relevance_raw`.

Cette étape évite d'appliquer une actualité sur le pétrole à une stratégie sur le sucre, par exemple.

### 14.4 Indicateurs news agrégés

Script :

```text
scripts/nlp/compute_news_indicators.py
```

Ce qu'il fait :

- agrège les signaux textuels par date et commodity ;
- calcule des indicateurs métier comme :
  - `weighted_sentiment_score` ;
  - `news_acceleration` ;
  - `geopolitical_risk_score` ;
  - `supply_shock_score`.
- écrit les résultats dans `raw.news_features_raw`.

Ces variables sont ensuite reprises par dbt, puis par la stratégie `technical_news_filter`.

Option rapide pour un environnement de test :

```bash
make nlp-mock
```

Cette commande lance une version mockée des embeddings et du sentiment. Elle est utile si tu veux tester le pipeline sans attendre les modèles NLP complets.

---

## 15. Construire les modèles dbt

```bash
make dbt-run
```

Ce que cela lance :

```bash
python scripts/extract_load/ensure_raw_tables.py
cd dbt_finance && dbt run --profiles-dir .
```

Ce que cela fait :

- recrée ou met à jour les modèles dbt ;
- lit les données brutes depuis `raw` ;
- construit les vues landing et staging ;
- construit les tables warehouse ;
- construit les marts finaux dans `mart`.

Flux dbt simplifié :

```text
raw
│
▼
landing
│
▼
staging
│
▼
warehouse
│
▼
mart
```

Exemples de transformations :

- `stg_commodity_prices` nettoie et type les prix ;
- `stg_benchmarks` prépare le benchmark ;
- `int_tradable_assets` expose les commodities et `COMMODITY_INDEX` comme actifs backtestables ;
- `int_technical_indicators` calcule SMA, RSI, Stochastic RSI, rendements et volatilité ;
- `int_commodity_news_features` prépare les variables issues du NLP ;
- `int_strategy_signals` calcule les signaux des stratégies ;
- `mart_backtest_daily`, `mart_backtest_trades` et `mart_strategy_metrics` alimentent le dashboard.

---

## 16. Tester les modèles dbt

```bash
make dbt-test
```

Ce que cela lance :

```bash
python scripts/extract_load/ensure_raw_tables.py
cd dbt_finance && dbt test --profiles-dir .
```

Ce que cela vérifie :

- unicité de certaines clés ;
- présence de valeurs obligatoires ;
- cohérence des relations entre modèles ;
- contraintes métier déclarées dans les fichiers `schema.yml`.

Cette étape ne sert pas à créer la donnée, mais à détecter les incohérences avant d'utiliser le dashboard ou d'interpréter les résultats.

---

## 17. Option recommandée : construire et tester en une commande

```bash
make dbt-build
```

Ce que cela lance :

```bash
python scripts/extract_load/ensure_raw_tables.py
cd dbt_finance && dbt build --profiles-dir .
```

`dbt build` combine :

- `dbt run` ;
- `dbt test`.

Si tu veux une reconstruction propre avant analyse, c'est souvent la meilleure commande après `make ingest` et `make nlp`.

---

## 18. Lancer le pipeline complet en une fois

```bash
make orchestrate
```

Ce que cela lance :

```bash
python scripts/orchestrate.py
```

Cette commande exécute tout le pipeline dans l'ordre :

```text
ingestion marché
ingestion benchmark
ingestion RSS
NLP
création des tables raw si besoin
dbt run
dbt test
mise à jour des marts de backtesting
```

Elle écrit aussi un fichier de log dans :

```text
logs/pipeline_<run_id>.csv
```

Chaque ligne du log contient :

- le nom de la tâche ;
- l'heure de début ;
- l'heure de fin ;
- le statut ;
- la durée ;
- le nombre de lignes si disponible ;
- le message d'erreur si la tâche échoue.

Cette commande est pratique une fois que tout est configuré. Pour un premier lancement, il est souvent plus lisible de lancer les étapes séparément dans l'ordre :

```bash
make ingest
make nlp
make dbt-build
```

---

## 19. Lancer les tests Python du repo

```bash
make test
```

Ce que cela lance :

```bash
pytest
```

Ce que cela vérifie :

- les règles de stratégie ;
- les fonctions du dashboard ;
- la cohérence du projet dbt ;
- la documentation attendue ;
- les comportements d'orchestration.

Cette étape est utile après une modification de code ou de SQL.

---

## 20. Lancer l'audit sécurité local

```bash
make security-audit
```

Ce que cela lance :

```bash
python scripts/security_audit.py
```

Ce que cela vérifie :

- absence de secrets évidents dans les fichiers versionnés ;
- cohérence des fichiers sensibles ignorés par Git ;
- risques simples liés aux credentials locaux.

Cette étape ne remplace pas un audit sécurité complet, mais elle évite les erreurs classiques comme commiter un fichier `.env` ou une clé JSON.

---

## 21. Lancer le dashboard Streamlit

```bash
make dashboard
```

Ce que cela lance :

```bash
PYTHONPATH=$(pwd) streamlit run dashboard/app.py --server.address=localhost --server.port=8501 --server.headless=false --browser.serverAddress=localhost
```

Ce que cela fait :

- démarre l'application Streamlit ;
- expose l'URL locale `http://localhost:8501` ;
- charge les marts BigQuery depuis le dataset `mart` ;
- affiche les outils de backtesting et de comparaison.

Si le navigateur mouline dans le vide, ouvre directement :

```text
http://localhost:8501
```

Si le port `8501` est déjà occupé par une ancienne session Streamlit, lance temporairement :

```bash
make dashboard STREAMLIT_PORT=8502
```

Puis ouvre :

```text
http://localhost:8502
```

Pages disponibles :

- `Backtest` : tester une ou plusieurs stratégies sur un actif, un capital initial et une période ;
- `Comparaison` : comparer les stratégies entre elles et mesurer l'apport du filtre RSS/NLP.

Actifs disponibles :

- les commodities issues de `config/commodities.yml` ;
- l'index synthétique `COMMODITY_INDEX`, construit à partir du benchmark.

Si le dashboard indique qu'une table comme `mart.mart_dashboard_overview` est introuvable, cela signifie généralement que les marts dbt n'ont pas encore été construits. Dans ce cas :

```bash
make dbt-build
make dashboard
```

Si le dashboard affiche une donnée ancienne, utilise le bouton :

```text
Rafraîchir les données
```

ou redémarre Streamlit.

---

## 22. Ordre de lancement recommandé depuis zéro

Voici la séquence complète, dans l'ordre :

```bash
cd /Users/alexandremasson/Desktop/Ynov/Projet-outil-ETL

python3.12 -m venv .venv
source .venv/bin/activate
make install

gcloud auth login
gcloud auth application-default login
gcloud config set project elt-commodities-backtesting
gcloud auth application-default set-quota-project elt-commodities-backtesting

cp .env.example .env
set -a
source .env
set +a

make infra-destroy
make infra-init
make infra-validate
make infra-plan
make infra-apply

make dbt-deps
make dbt-ensure-raw
python scripts/orchestrate.py --dry-run

make ingest
make nlp
make dbt-build

make test
make security-audit
make dashboard
```

Si `.env` existe déjà, ne refais pas forcément :

```bash
cp .env.example .env
```

car cela pourrait écraser ta configuration locale si tu utilises une commande avec redirection ou copie forcée.

---

## 23. Version courte pour les prochains lancements

Une fois l'environnement déjà configuré :

```bash
cd /Users/alexandremasson/Desktop/Ynov/Projet-outil-ETL
source .venv/bin/activate
set -a
source .env
set +a

make ingest
make nlp
make dbt-build
make dashboard
```

Version orchestrée :

```bash
source .venv/bin/activate
set -a
source .env
set +a

make orchestrate
make dashboard
```

---

## 24. Points de contrôle dans BigQuery

Après `make ingest`, vérifier dans BigQuery :

```text
raw.market_data_raw
raw.benchmarks_raw
raw.news_raw
```

Après `make nlp`, vérifier :

```text
raw.news_embeddings_raw
raw.news_sentiment_raw
raw.article_commodity_relevance_raw
raw.news_features_raw
```

Après `make dbt-build`, vérifier :

```text
dbt_finance.stg_commodity_prices
dbt_finance.int_tradable_assets
dbt_finance.int_technical_indicators
dbt_finance.int_strategy_signals
mart.mart_backtest_daily
mart.mart_backtest_trades
mart.mart_strategy_metrics
mart.mart_dashboard_overview
```

Si ces tables existent et contiennent des lignes, le pipeline est exploitable par Streamlit.

---

## 25. Commandes de diagnostic utiles

Vérifier le projet GCP actif :

```bash
gcloud config get-value project
```

Vérifier les credentials applicatifs :

```bash
gcloud auth application-default print-access-token
```

Vérifier dbt :

```bash
cd dbt_finance
dbt debug --profiles-dir .
cd ..
```

Lister les tâches orchestrées sans les lancer :

```bash
python scripts/orchestrate.py --dry-run
```

Lire le dernier log pipeline :

```bash
ls -lt logs/pipeline_*.csv | head
```

Puis ouvrir le fichier le plus récent pour voir quelle tâche a échoué.

---

## 26. Résumé mental du flux complet

```text
Terraform
  crée les datasets BigQuery et les droits IAM

Python ingest
  charge les prix, benchmarks et articles RSS dans raw

Python NLP
  transforme les articles en scores textuels dans raw

dbt
  nettoie, joint, enrichit et matérialise les tables analytiques

Backtesting dbt
  calcule les signaux, trades, courbes et métriques

Streamlit
  lit les marts et permet de comparer les stratégies
```

La logique importante est donc :

```text
infra d'abord
raw ensuite
NLP ensuite
dbt ensuite
dashboard à la fin
```
