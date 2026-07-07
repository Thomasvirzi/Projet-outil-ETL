# Architecture globale

Ce document synthétise l'architecture finale du projet.

---

## 1. Vue d'ensemble

```text
Yahoo Finance
Flux RSS
    │
    ▼
Scripts Python d'ingestion
    │
    ▼
BigQuery raw
    │
    ├── NLP Python
    │   ├── embeddings
    │   ├── sentiment
    │   ├── pertinence article-matière première
    │   └── indicateurs textuels
    │
    ▼
dbt
    ├── landing
    ├── staging
    ├── warehouse
    │   ├── univers tradable
    │   ├── indicateurs techniques
    │   └── signaux de stratégies
    └── marts
        │
        ├── moteur de backtesting
        └── dashboard Streamlit Backtest Lab
```

---

## 2. Composants

| Composant | Rôle |
| --- | --- |
| `config/` | Paramètres fonctionnels du pipeline |
| `scripts/extract_load/` | Ingestion Yahoo Finance, benchmarks et RSS |
| `scripts/nlp/` | Embeddings, sentiment, pertinence et features news |
| `dbt_finance/` | Transformations ELT et tests dbt |
| `backtesting/` | Moteur de simulation, stratégies, coûts et métriques |
| `dashboard/` | Interface Streamlit recentrée sur Backtest et Comparaison |
| `scripts/orchestrate.py` | Orchestration quotidienne |
| `infrastructure/` | Terraform GCP/BigQuery |
| `tests/` | Recette automatisée |

---

## 3. Datasets BigQuery

| Dataset | Rôle |
| --- | --- |
| `raw` | Données brutes ingérées |
| `dbt_finance` | Modèles dbt intermédiaires selon la cible |
| `mart` | Tables finales dashboard/backtesting |

Une macro dbt force cet alignement :

```text
dbt_finance/macros/generate_schema_name.sql
```

Ainsi :

```text
landing/staging/warehouse → dbt_finance
marts                     → mart
```

---

## 4. Tables principales

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

Marts principaux :

```text
mart_strategy_signals
mart_backtest_daily
mart_backtest_trades
mart_strategy_metrics
mart_dashboard_overview
mart_validation_period_metrics
mart_rss_filter_contribution
```

Modèles warehouse structurants :

```text
int_tradable_assets
int_technical_indicators
int_commodity_news_features
int_strategy_signals
int_daily_returns
```

`int_tradable_assets` crée l'univers backtestable. Il regroupe les matières premières issues de `stg_commodity_prices` et l'indice synthétique `COMMODITY_INDEX` issu de `stg_benchmarks`.

---

## 5. Garanties méthodologiques

Le projet applique plusieurs garde-fous :

```text
déduplication symbol/date ;
déduplication article_id ;
signal exécuté à J+1 ;
pas de vente à découvert dans le MVP ;
frais et slippage intégrés ;
split calibration / validation / test final ;
indice synthétique testable comme actif ;
tests dbt critiques ;
audit secrets ;
limite de coût BigQuery.
```
