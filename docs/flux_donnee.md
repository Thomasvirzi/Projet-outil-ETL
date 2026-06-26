# Flux de la donnée

Ce document explique le trajet de la donnée dans le projet, depuis les sources externes jusqu'au dashboard Streamlit.

L'objectif est d'avoir un pipeline lisible :

```text
Sources externes
→ scripts d'extraction
→ fichiers locaux temporaires
→ BigQuery raw
→ transformations dbt
→ BigQuery marts
→ backtesting et dashboard Streamlit
```

---

## 1. Vue d'ensemble

```mermaid
flowchart TD
    A["Yahoo Finance API"] --> B["scripts/extract_load/ingest_commodities.py"]
    C["Flux RSS financiers"] --> D["scripts/extract_load/ingest_rss.py"]
    E["Yahoo Finance API - benchmark"] --> F["scripts/extract_load/ingest_benchmarks.py"]

    B --> G["data/raw/market_data/*.csv"]
    D --> H["data/raw/news/*.csv"]
    F --> I["data/raw/benchmarks/*.csv"]

    G --> J["scripts/extract_load/load_to_bigquery.py"]
    H --> J
    I --> J

    J --> K["BigQuery raw"]
    K --> L["dbt_finance/models/landing"]
    L --> M["dbt_finance/models/staging"]
    M --> N["dbt_finance/models/warehouse"]
    N --> O["dbt_finance/models/marts"]

    O --> P["backtesting/"]
    O --> Q["dashboard/"]
```

> Les fichiers CSV dans `data/raw/` servent de zone tampon locale. Ils sont pratiques pour déboguer, rejouer une ingestion et vérifier les données avant chargement. L'arborescence `data/` est suivie via des `.gitkeep`, mais son contenu runtime est ignoré par Git.

---

## 2. Dossiers importants

| Dossier | Rôle |
| --- | --- |
| `config/` | Contient les paramètres du pipeline : tickers, benchmarks, RSS, stratégies. |
| `scripts/extract_load/` | Contient les scripts d'extraction et de chargement des données brutes. |
| `scripts/nlp/` | Contient les scripts d'embeddings, pertinence, sentiment et indicateurs textuels. |
| `data/raw/` | Zone locale temporaire pour les CSV extraits depuis les APIs ; contenu ignoré par Git. |
| `data/processed/` | Zone locale temporaire pour les fichiers nettoyés ou enrichis ; contenu ignoré par Git. |
| `dbt_finance/` | Projet dbt qui transforme les tables BigQuery. |
| `backtesting/` | Moteur de backtesting consommant les tables mart. |
| `dashboard/` | Application Streamlit consommant les tables mart. |
| `logs/` | Logs locaux du pipeline et erreurs ; contenu ignoré par Git. |

---

## 3. Flux données de marché

### 3.1 Configuration

Les matières premières et tickers sont définis dans :

```text
config/commodities.yml
```

Exemple attendu :

```yaml
commodities:
  - symbol: GC=F
    name: Gold Futures
    category: precious_metals
  - symbol: CL=F
    name: Crude Oil WTI Futures
    category: energy
```

### 3.2 Extraction depuis Yahoo Finance

Script responsable :

```text
scripts/extract_load/ingest_commodities.py
```

Rôle du script :

1. lire `config/commodities.yml` ;
2. appeler l'API Yahoo Finance avec `yfinance` ;
3. récupérer les champs OHLCV ;
4. normaliser les noms de colonnes ;
5. ajouter `symbol`, `source` et `ingested_at` ;
6. écrire un CSV local dans `data/raw/market_data/`.

Fichier produit :

```text
data/raw/market_data/market_data_YYYYMMDD.csv
```

Schéma attendu :

```text
symbol
date
open
high
low
close
adjusted_close
volume
source
ingested_at
```

### 3.3 Chargement vers BigQuery

Script responsable :

```text
scripts/extract_load/load_to_bigquery.py
```

Rôle du script :

1. lire le dernier CSV dans `data/raw/market_data/` ;
2. contrôler les colonnes attendues ;
3. supprimer les doublons locaux sur `symbol` + `date` ;
4. charger les lignes dans BigQuery ;
5. éviter les doublons lors d'une relance.

Table BigQuery cible :

```text
raw.market_data_raw
```

---

## 4. Flux benchmarks

Un benchmark est une référence de comparaison.

Dans ce projet, il ne sert pas à prendre une décision d'achat ou de vente. Il sert à répondre à une question simple :

> Est-ce que ma stratégie fait mieux qu'une méthode de référence simple ?

Il y a deux familles de benchmarks dans le projet :

| Benchmark | Rôle | Exemple |
| --- | --- | --- |
| Buy and Hold | Acheter une matière première au début de la période et la garder jusqu'à la fin. | Acheter `GC=F` en 2020 et conserver jusqu'à J-1. |
| Benchmark global | Représenter le marché global des matières premières. | ETF ou indice diversifié comme `DBC`. |

Exemple :

```text
Si une stratégie sur l'or gagne +18 %, mais que Buy and Hold sur l'or gagne +25 %,
alors la stratégie est moins intéressante que simplement acheter et conserver l'or.

Si une stratégie gagne +18 %, mais que le benchmark global commodities gagne +8 %,
alors elle surperforme le marché global des matières premières.
```

Le benchmark est donc une base de comparaison, pas une source de signal.

### 4.1 Configuration

Les benchmarks sont définis dans :

```text
config/benchmarks.yml
```

Exemple attendu :

```yaml
benchmarks:
  global:
    symbol: DBC
    name: Invesco DB Commodity Index Tracking Fund

  buy_and_hold:
    enabled: true
```

Dans cet exemple :

- `DBC` représente le benchmark global ;
- `buy_and_hold.enabled: true` indique que chaque matière première sera aussi comparée à sa propre performance passive.

### 4.2 Extraction

Script responsable :

```text
scripts/extract_load/ingest_benchmarks.py
```

Rôle du script :

1. lire `config/benchmarks.yml` ;
2. récupérer le benchmark global via Yahoo Finance ;
3. récupérer les données de prix nécessaires aux comparaisons ;
4. normaliser les champs ;
5. écrire un CSV local.

Fichier produit :

```text
data/raw/benchmarks/benchmarks_YYYYMMDD.csv
```

Exemple de contenu :

```csv
benchmark_id,benchmark_type,symbol,date,open,high,low,close,adjusted_close,volume,source,ingested_at
global_dbc,global,DBC,2024-01-02,22.10,22.31,22.05,22.25,22.25,1530000,yahoo_finance,2026-06-26T08:00:00Z
global_dbc,global,DBC,2024-01-03,22.25,22.40,22.12,22.18,22.18,1480000,yahoo_finance,2026-06-26T08:00:00Z
buy_hold_gc,buy_and_hold,GC=F,2024-01-02,2072.70,2088.10,2065.20,2078.40,2078.40,145321,yahoo_finance,2026-06-26T08:00:00Z
buy_hold_gc,buy_and_hold,GC=F,2024-01-03,2078.40,2082.90,2048.00,2055.70,2055.70,151884,yahoo_finance,2026-06-26T08:00:00Z
```

Schéma attendu :

```text
benchmark_id
benchmark_type
symbol
date
open
high
low
close
adjusted_close
volume
source
ingested_at
```

Différence avec `market_data_raw` :

- `market_data_raw` contient les prix des instruments étudiés pour générer indicateurs et signaux ;
- `benchmarks_raw` contient les prix des références utilisées pour comparer les résultats ;
- une même matière première peut apparaître dans les deux logiques : comme instrument tradé dans `market_data_raw`, et comme référence Buy and Hold dans `benchmarks_raw`.

### 4.3 Chargement vers BigQuery

Script responsable :

```text
scripts/extract_load/load_to_bigquery.py
```

Table BigQuery cible :

```text
raw.benchmarks_raw
```

Utilisation après chargement :

```text
raw.benchmarks_raw
→ stg_benchmarks
→ mart_strategy_metrics
→ dashboard/pages/06_comparison.py
```

Le backtesting utilise ensuite ces données pour calculer :

- la performance du benchmark sur la même période ;
- la surperformance ou sous-performance de la stratégie ;
- les graphiques de comparaison entre stratégie, Buy and Hold et benchmark global.

---

## 5. Flux actualités RSS

### 5.1 Configuration

Les flux RSS sont définis dans :

```text
config/rss_sources.yml
```

Exemple attendu :

```yaml
rss_sources:
  - name: Investing Commodities
    url: https://example.com/rss/commodities
    category: commodities
```

### 5.2 Extraction RSS

Script responsable :

```text
scripts/extract_load/ingest_rss.py
```

Rôle du script :

1. lire `config/rss_sources.yml` ;
2. appeler chaque flux RSS avec `feedparser` ;
3. récupérer titre, source, URL, date et résumé ;
4. nettoyer le HTML avec BeautifulSoup ;
5. calculer `article_id` et `content_hash` ;
6. supprimer les doublons exacts ;
7. écrire un CSV local.

Fichier produit :

```text
data/raw/news/news_YYYYMMDD.csv
```

Schéma attendu :

```text
article_id
title
source
url
published_at
clean_text
content_hash
ingested_at
```

### 5.3 Chargement vers BigQuery

Script responsable :

```text
scripts/extract_load/load_to_bigquery.py
```

Table BigQuery cible :

```text
raw.news_raw
```

---

## 6. Flux NLP

Les données textuelles chargées dans BigQuery sont ensuite enrichies par les scripts NLP.

Point important : **FinBERT et les embeddings ne sont pas calculés directement dans dbt**.

dbt est excellent pour transformer des tables avec du SQL : nettoyer, typer, joindre, dédupliquer, agréger. En revanche, charger un modèle NLP comme FinBERT ou Sentence Transformers est un traitement Python.

Dans ce projet, la séparation recommandée est donc :

| Étape | Outil | Rôle |
| --- | --- | --- |
| Nettoyage simple des articles | dbt Staging | Préparer `stg_news` depuis `raw.news_raw`. |
| Embeddings | Python | Charger Sentence Transformers et écrire les vecteurs. |
| Sentiment FinBERT | Python | Charger FinBERT et calculer les probabilités positive, neutre, négative. |
| Pertinence article-matière première | Python | Comparer les embeddings article et commodity. |
| Agrégation finale | dbt Warehouse | Construire les indicateurs journaliers par matière première. |
| Exposition dashboard/backtesting | dbt Marts | Produire les tables finales propres. |

Le flux recommandé est donc hybride :

```text
raw.news_raw
→ dbt staging : stg_news
→ scripts Python NLP lisent stg_news
→ scripts Python NLP écrivent des tables raw NLP
→ dbt warehouse lit ces tables raw NLP
→ dbt marts expose les résultats
```

Pourquoi ne pas écrire directement dans `dbt_finance` ou `mart` depuis Python ?

- pour garder dbt responsable des tables transformées ;
- pour éviter que Python et dbt modifient les mêmes tables ;
- pour conserver une séparation claire entre résultats bruts de modèles et tables métier ;
- pour pouvoir rejouer dbt sans relancer FinBERT à chaque fois.

Les scripts Python NLP écrivent donc plutôt dans des tables brutes ou semi-brutes :

```text
raw.news_embeddings_raw
raw.news_sentiment_raw
raw.article_commodity_relevance_raw
raw.news_features_raw
```

Puis dbt construit les modèles :

```text
stg_news_embeddings
stg_news_sentiment
stg_article_commodity_relevance
int_commodity_news_features
mart_dashboard_overview
mart_strategy_signals
```

### 6.1 Embeddings

Script responsable :

```text
scripts/nlp/create_embeddings.py
```

Entrée :

```text
stg_news
```

Sortie possible :

```text
raw.news_embeddings_raw
```

Rôle du script :

1. lire les articles nettoyés sans embedding depuis `stg_news` ;
2. générer un vecteur avec le modèle défini dans `.env` ;
3. historiser le modèle et sa version ;
4. éviter de recalculer les embeddings déjà présents.

Schéma attendu :

```text
article_id
embedding
embedding_model
embedding_version
created_at
```

### 6.2 Pertinence article-matière première

Script responsable :

```text
scripts/nlp/compute_relevance.py
```

Entrées :

```text
raw.news_embeddings_raw
config/commodities.yml
```

Sortie possible :

```text
raw.article_commodity_relevance_raw
```

Rôle du script :

1. créer une description de référence par matière première ;
2. générer ou charger son embedding ;
3. comparer chaque article à chaque matière première ;
4. calculer une similarité cosinus ;
5. appliquer un seuil de pertinence.

Schéma attendu :

```text
article_id
commodity_symbol
similarity_score
is_relevant
calculated_at
```

### 6.3 Sentiment et indicateurs textuels

Deux traitements sont à distinguer :

1. le sentiment FinBERT, fait en Python ;
2. l'agrégation finale des indicateurs textuels, faite de préférence avec dbt.

Script responsable du sentiment :

```text
scripts/nlp/compute_sentiment.py
```

Entrée :

```text
stg_news
```

Sortie possible :

```text
raw.news_sentiment_raw
```

Rôle du script :

1. lire les articles nettoyés depuis `stg_news` ;
2. charger un modèle FinBERT ou équivalent financier ;
3. calculer `positive_probability`, `neutral_probability` et `negative_probability` ;
4. calculer `sentiment_score` ;
5. écrire les résultats dans BigQuery.

Formule recommandée :

```text
sentiment_score = positive_probability - negative_probability
```

Schéma attendu :

```text
article_id
positive_probability
neutral_probability
negative_probability
sentiment_score
sentiment_model
sentiment_model_version
calculated_at
```

Script responsable de la préparation des features textuelles :

```text
scripts/nlp/compute_news_indicators.py
```

Entrées :

```text
stg_news
raw.news_embeddings_raw
raw.news_sentiment_raw
raw.article_commodity_relevance_raw
```

Sortie possible :

```text
raw.news_features_raw
```

Rôle du script :

1. calculer la nouveauté ;
2. préparer les scores article-matière première ;
3. produire des features textuelles brutes ou semi-agrégées ;
4. laisser dbt construire `int_commodity_news_features`.

Indicateurs attendus :

```text
commodity_symbol
date
news_pressure_score
news_surprise_20d
news_volume
novelty_score
sentiment_dispersion
```

---

## 7. Transformations dbt

Une fois les données chargées dans le dataset `raw`, dbt prépare les tables propres et exploitables.

### 7.1 Landing

Dossier :

```text
dbt_finance/models/landing/
```

Rôle :

- créer des vues simples sur les tables `raw` ;
- ne pas appliquer de logique métier complexe.

Exemples :

```text
landing_market_data.sql
landing_news.sql
landing_benchmarks.sql
```

### 7.2 Staging

Dossier :

```text
dbt_finance/models/staging/
```

Rôle :

- renommer les colonnes ;
- caster les types ;
- dédupliquer ;
- ajouter des contrôles qualité ;
- préparer les données pour les calculs.

Modèles attendus :

```text
stg_commodity_prices
stg_benchmarks
stg_news
stg_pipeline_logs
```

### 7.3 Warehouse

Dossier :

```text
dbt_finance/models/warehouse/
```

Rôle :

- calculer les indicateurs techniques ;
- calculer les indicateurs textuels ;
- construire les signaux de stratégie ;
- préparer les rendements journaliers.

Modèles attendus :

```text
int_technical_indicators
int_article_commodity_relevance
int_commodity_news_features
int_strategy_signals
int_daily_returns
```

### 7.4 Marts

Dossier :

```text
dbt_finance/models/marts/
```

Rôle :

- créer les tables finales utilisées par le backtesting et le dashboard.

Modèles attendus :

```text
mart_strategy_signals
mart_backtest_trades
mart_backtest_daily
mart_strategy_metrics
mart_dashboard_overview
```

---

## 8. Backtesting

Le moteur de backtesting consomme les tables `mart`.

Entrées principales :

```text
mart_strategy_signals
mart_dashboard_overview
mart_commodity_news_features
```

Dossier :

```text
backtesting/
```

Scripts prévus :

```text
backtesting/engine.py
backtesting/portfolio.py
backtesting/costs.py
backtesting/metrics.py
backtesting/strategies/
```

Sorties principales :

```text
mart_backtest_trades
mart_backtest_daily
mart_strategy_metrics
```

Règles importantes :

- un signal calculé à J est exécuté au plus tôt à J+1 ;
- aucune donnée future ne doit être utilisée ;
- les frais et le slippage doivent être intégrés ;
- chaque backtest doit conserver ses paramètres.

---

## 9. Dashboard Streamlit

Le dashboard lit uniquement les tables propres du dataset `mart`.

Dossier :

```text
dashboard/
```

Services :

```text
dashboard/services/bigquery_client.py
dashboard/services/data_loader.py
```

Pages prévues :

```text
dashboard/pages/01_market_overview.py
dashboard/pages/02_indicators.py
dashboard/pages/03_news_indicators.py
dashboard/pages/04_strategy_explorer.py
dashboard/pages/05_backtest.py
dashboard/pages/06_comparison.py
dashboard/pages/07_data_quality.py
```

Flux :

```text
BigQuery mart
→ dashboard/services/data_loader.py
→ pages Streamlit
→ graphiques, filtres et exports CSV
```

---

## 10. Orchestration quotidienne

Script responsable :

```text
scripts/orchestrate.py
```

Ordre d'exécution cible :

```text
1. scripts/extract_load/ingest_commodities.py
2. scripts/extract_load/ingest_benchmarks.py
3. scripts/extract_load/ingest_rss.py
4. scripts/extract_load/load_to_bigquery.py
5. dbt run --select models/landing models/staging
6. scripts/nlp/create_embeddings.py
7. scripts/nlp/compute_sentiment.py
8. scripts/nlp/compute_relevance.py
9. scripts/nlp/compute_news_indicators.py
10. dbt run --select models/warehouse models/marts
11. dbt test
12. backtesting/engine.py
13. écriture du statut final du pipeline
```

Cette organisation permet aux scripts NLP de lire des articles déjà nettoyés dans `stg_news`, tout en laissant dbt construire les tables analytiques finales.

Chaque étape doit produire un log :

```text
run_id
task_name
start_time
end_time
status
rows_processed
error_message
```

Logs locaux possibles :

```text
logs/pipeline_YYYYMMDD.log
```

Table BigQuery possible :

```text
raw.pipeline_logs_raw
```

---

## 11. Exemple concret de trajet d'une donnée prix

Exemple : prix de clôture de l'or.

```text
1. Le ticker GC=F est défini dans config/commodities.yml.
2. scripts/extract_load/ingest_commodities.py appelle Yahoo Finance.
3. Le script récupère date, open, high, low, close, adjusted_close et volume.
4. Il écrit data/raw/market_data/market_data_20260626.csv.
5. scripts/extract_load/load_to_bigquery.py lit ce CSV.
6. Le loader insère les lignes dans raw.market_data_raw.
7. dbt crée stg_commodity_prices depuis raw.market_data_raw.
8. dbt calcule int_technical_indicators.
9. dbt produit mart_strategy_signals et mart_dashboard_overview.
10. backtesting/engine.py lit mart_strategy_signals pour tester les stratégies.
11. dashboard/pages/01_market_overview.py lit mart_dashboard_overview pour afficher les graphiques.
```

---

## 12. Exemple concret de trajet d'une actualité

Exemple : article RSS sur le pétrole.

```text
1. L'URL du flux RSS est définie dans config/rss_sources.yml.
2. scripts/extract_load/ingest_rss.py lit le flux avec feedparser.
3. Le script extrait title, source, url, published_at et clean_text.
4. Il calcule article_id et content_hash.
5. Il écrit data/raw/news/news_20260626.csv.
6. scripts/extract_load/load_to_bigquery.py charge le CSV dans raw.news_raw.
7. dbt crée stg_news avec les articles nettoyés et typés.
8. scripts/nlp/create_embeddings.py lit stg_news et génère l'embedding de l'article.
9. scripts/nlp/compute_sentiment.py lit stg_news et calcule le score FinBERT.
10. scripts/nlp/compute_relevance.py compare l'article aux matières premières.
11. scripts/nlp/compute_news_indicators.py prépare nouveauté et features textuelles.
12. Les scripts NLP écrivent leurs résultats dans des tables raw NLP.
13. dbt prépare int_commodity_news_features depuis ces tables raw NLP.
14. dbt alimente mart_strategy_signals et mart_dashboard_overview.
15. La stratégie technical_news_filter utilise le signal textuel.
16. dashboard/pages/03_news_indicators.py affiche la pression des actualités.
```

---

## 13. Convention de nommage proposée

Fichiers locaux :

```text
data/raw/market_data/market_data_YYYYMMDD.csv
data/raw/benchmarks/benchmarks_YYYYMMDD.csv
data/raw/news/news_YYYYMMDD.csv
data/processed/news_embeddings/news_embeddings_YYYYMMDD.parquet
logs/pipeline_YYYYMMDD.log
```

Tables BigQuery brutes :

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

Tables BigQuery finales :

```text
mart.mart_strategy_signals
mart.mart_backtest_trades
mart.mart_backtest_daily
mart.mart_strategy_metrics
mart.mart_dashboard_overview
```

---

## 14. Points à décider plus tard

Ces éléments dépendent de l'étape 0 de cadrage :

- liste finale des matières premières ;
- tickers Yahoo Finance ;
- benchmark global ;
- sources RSS ;
- date de début définitive : `2020-01-01` ou historique plus ancien ;
- seuil de pertinence RSS ;
- modèle exact de sentiment financier.
