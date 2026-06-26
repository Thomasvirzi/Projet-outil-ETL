# Note de cadrage — Pipeline ELT et backtesting sur les matières premières

**Cadre :** Projet M1 Ynov Data & IA — 2025-2026

**Présentation finale :** 7 juillet 2026

**Version :** 3.0

---

## 1. Contexte et objectif

Le projet consiste à construire une plateforme de données financières dédiée à l’étude des matières premières.

La plateforme devra collecter quotidiennement des données de marché et des actualités financières, les stocker dans Google BigQuery, calculer des indicateurs techniques et textuels, puis exécuter plusieurs stratégies de trading fondées sur des règles explicables.

Les résultats seront comparés à des stratégies passives et visualisés dans un dashboard Streamlit.

### Objectif principal

> Construire un pipeline ELT automatisé couvrant plusieurs matières premières sur la période allant du 1er janvier 2020 à J-1, afin de calculer des indicateurs financiers et sémantiques, d’exécuter des backtests de stratégies quantitatives et de comparer leurs performances à des benchmarks pertinents.
> 

### Question de recherche

> L’ajout d’un indicateur construit à partir des actualités financières améliore-t-il le rendement ajusté du risque d’une stratégie technique appliquée aux matières premières ?
> 

---

## 2. Périmètre fonctionnel

| Paramètre | Valeur |
| --- | --- |
| Univers | 10 à 15 matières premières |
| Historique | 01/01/2020 à J-1 |
| Fréquence | Données journalières |
| Exécution | Un pipeline automatisé par jour après la clôture |
| Données de marché | Prix OHLCV et benchmarks |
| Données textuelles | Articles issus de flux RSS financiers |
| Approche | Backtesting de règles quantitatives |
| Infrastructure | Google Cloud et BigQuery provisionnés avec Terraform |
| Transformation | dbt |
| Restitution | Dashboard Streamlit |

---

## 3. Univers étudié

L’univers sera fixé en début de projet et pourra contenir les instruments suivants.

| Catégorie | Exemples |
| --- | --- |
| Métaux précieux | Or, argent, platine |
| Énergie | Pétrole WTI, Brent, gaz naturel |
| Métaux industriels | Cuivre |
| Agriculture | Blé, maïs, soja, café, sucre |

Les données pourront provenir de contrats futures continus accessibles via Yahoo Finance.

Les limites liées à l’utilisation de futures devront être documentées, notamment :

- les changements de contrats ;
- les effets de roulement ;
- les différences entre prix spot et prix futures ;
- les périodes de faible liquidité.

---

## 4. Sources de données

### 4.1 Données de marché

La source principale sera Yahoo Finance via la bibliothèque `yfinance`.

Données collectées :

- date ;
- open ;
- high ;
- low ;
- close ;
- adjusted close, si disponible ;
- volume ;
- symbole de l’instrument.

Le script d’ingestion devra gérer :

- les tentatives automatiques en cas d’échec ;
- la déduplication ;
- l’idempotence ;
- la journalisation des erreurs ;
- la conservation du dernier run valide.

### 4.2 Benchmarks

Chaque stratégie sera comparée à deux références :

1. une stratégie Buy and Hold sur la matière première concernée ;
2. un indice ou un ETF diversifié représentatif du marché des matières premières.

Le Buy and Hold constituera la baseline principale.

### 4.3 Flux RSS financiers

Les flux RSS permettront de collecter des articles liés :

- aux matières premières ;
- aux décisions de production ;
- aux stocks ;
- aux conditions climatiques ;
- aux tensions géopolitiques ;
- à la demande mondiale ;
- au transport et à la logistique ;
- aux politiques monétaires.

Les articles seront nettoyés, normalisés et dédupliqués à l’ingestion.

La déduplication reposera sur :

- un hash du titre et de la date ;
- une comparaison sémantique entre les embeddings des articles.

---

## 5. Infrastructure avec Terraform

Terraform sera utilisé pour décrire et provisionner l’infrastructure Google Cloud.

BigQuery étant un service serverless, Terraform ne créera pas une machine ou une instance dédiée. Il provisionnera les ressources nécessaires au projet.

### Ressources principales

- activation des API Google Cloud ;
- datasets BigQuery ;
- service account du pipeline ;
- rôles et permissions IAM ;
- éventuel bucket Cloud Storage ;
- paramètres de localisation et de sécurité.

### Datasets BigQuery

| Dataset | Contenu |
| --- | --- |
| `raw` | Données de marché, articles RSS et logs bruts |
| `dbt_finance` | Modèles de préparation et de transformation |
| `mart` | Tables destinées aux backtests et au dashboard |

### Structure Terraform

```
infrastructure/
├── main.tf
├── providers.tf
├── variables.tf
├── outputs.tf
├── bigquery.tf
├── iam.tf
└── environments/
    └── dev.tfvars
```

---

## 6. Architecture ELT

### 6.1 Extract et Load — Python

Les scripts Python assureront l’ingestion des données dans BigQuery.

```
scripts/
├── extract_load/
│   ├── config.py
│   ├── ingest_commodities.py
│   ├── ingest_benchmarks.py
│   └── ingest_rss.py
└── orchestrate.py
```

### Séquence quotidienne

1. ingestion des cours des matières premières ;
2. ingestion des benchmarks ;
3. ingestion des articles RSS ;
4. création des embeddings et des scores textuels ;
5. exécution des modèles dbt ;
6. exécution des tests de qualité ;
7. mise à jour des backtests ;
8. journalisation du run.

L’orchestration pourra être réalisée avec APScheduler dans le cadre du projet académique.

---

## 7. Transformations avec dbt

L’organisation dbt comportera quatre couches.

| Couche | Rôle |
| --- | --- |
| Landing | Vues sur les tables brutes |
| Staging | Nettoyage, typage, déduplication et contrôles qualité |
| Warehouse | Calcul des indicateurs, signaux et agrégats textuels |
| Marts | Tables finales pour les backtests et Streamlit |

### Modèles principaux

### Staging

- `stg_commodity_prices`
- `stg_benchmarks`
- `stg_news`
- `stg_pipeline_logs`

### Warehouse

- `int_technical_indicators`
- `int_article_commodity_relevance`
- `int_commodity_news_features`
- `int_strategy_signals`
- `int_daily_returns`

### Marts

- `mart_strategy_signals`
- `mart_backtest_trades`
- `mart_backtest_daily`
- `mart_strategy_metrics`
- `mart_dashboard_overview`

### Tests dbt

Les tests devront couvrir :

- l’unicité du couple instrument-date ;
- l’absence de valeurs nulles critiques ;
- la validité des prix ;
- la cohérence des dates ;
- la validité des signaux ;
- la fraîcheur des données ;
- l’absence de doublons dans les articles.

---

## 8. Indicateurs techniques

Les indicateurs suivants pourront être calculés :

- moyenne mobile simple à 20 jours ;
- moyenne mobile simple à 50 jours ;
- moyenne mobile à 100 ou 200 jours ;
- RSI à 14 jours ;
- Stochastic RSI ;
- MACD ;
- bandes de Bollinger ;
- ATR ;
- volatilité historique ;
- rendements logarithmiques ;
- ratio de volume.

Les paramètres devront être configurables et documentés.

---

## 9. Indicateur textuel basé sur les embeddings

Les articles RSS seront convertis en représentations vectorielles à l’aide d’un modèle d’embedding léger.

L’objectif n’est pas de prédire directement les prix avec un modèle d’intelligence artificielle, mais de produire des indicateurs financiers structurés à partir de textes non structurés.

### Commodity News Pressure Index

Pour chaque article, quatre composantes seront calculées :

- pertinence pour la matière première ;
- sentiment financier ;
- nouveauté de l’information ;
- fraîcheur de l’article.

Un score pourra être défini ainsi :

[

ArticleScore =

Pertinence

\times Sentiment

\times Nouveauté

\times PoidsSource

]

Les scores seront ensuite agrégés quotidiennement par matière première.

### Indicateurs textuels produits

| Indicateur | Description |
| --- | --- |
| `news_pressure_score` | Pression positive ou négative des actualités |
| `news_surprise_20d` | Écart du score par rapport à sa moyenne sur 20 jours |
| `news_volume` | Nombre d’articles pertinents |
| `news_acceleration` | Hausse inhabituelle du volume d’articles |
| `novelty_score` | Caractère nouveau des informations |
| `sentiment_dispersion` | Niveau de désaccord entre les articles |
| `geopolitical_risk_score` | Intensité des sujets géopolitiques |
| `supply_shock_score` | Intensité des informations relatives à l’offre |
| `weather_risk_score` | Intensité des risques météorologiques |

Un modèle de sentiment financier pourra compléter le modèle d’embedding.

---

## 10. Stratégies de trading testées

### Stratégie 1 — Buy and Hold

Achat au début de la période et conservation jusqu’à la fin.

Cette stratégie constitue la baseline principale.

### Stratégie 2 — Croisement de moyennes mobiles

Signal d’achat lorsque la moyenne mobile courte croise au-dessus de la moyenne mobile longue.

Signal de sortie lorsque la moyenne mobile courte repasse sous la moyenne mobile longue.

### Stratégie 3 — Moyennes mobiles et Stochastic RSI

Signal d’achat lorsque :

- la moyenne mobile courte croise au-dessus de la moyenne mobile longue ;
- le Stochastic RSI confirme le momentum ;
- l’indicateur ne se trouve pas dans une zone de surachat excessive.

Signal de sortie lorsque :

- le croisement devient négatif ;
- le Stochastic RSI atteint une zone de surachat ;
- une règle de gestion du risque est déclenchée.

### Stratégie 4 — Technique avec filtre RSS

La stratégie technique est exécutée uniquement lorsque l’indicateur textuel confirme le signal.

Exemple :

```
Signal technique positif
ET news_pressure_score > 0
ET novelty_score supérieur au seuil défini
```

### Stratégie complémentaire

Une stratégie de breakout ou de retour à la moyenne pourra être ajoutée si le planning le permet.

---

## 11. Règles de backtesting

Les règles devront limiter les biais fréquents dans les analyses financières.

### Principes

- un signal calculé à la clôture de J ne peut être exécuté qu’à J+1 ;
- aucune donnée future ne doit intervenir dans la décision ;
- les frais de transaction doivent être intégrés ;
- un slippage pourra être simulé ;
- les paramètres ne devront pas être optimisés sur la période de test ;
- le capital initial sera identique pour toutes les stratégies.

### Découpage temporel

| Période | Utilisation |
| --- | --- |
| 2020–2023 | Conception et calibration |
| 2024 | Validation |
| 2025–J-1 | Évaluation finale hors échantillon |

### Capital et coûts

- capital initial : 100 000 € ;
- frais de transaction : hypothèse configurable ;
- exposition maximale : configurable ;
- prise en compte des coûts à chaque entrée et sortie.

---

## 12. Métriques de performance

Les stratégies seront comparées selon :

- rendement cumulé ;
- rendement annualisé ;
- volatilité annualisée ;
- ratio de Sharpe ;
- ratio de Sortino ;
- maximum drawdown ;
- ratio de Calmar ;
- win rate ;
- profit factor ;
- nombre de transactions ;
- durée moyenne des positions ;
- frais cumulés ;
- performance excédentaire par rapport au benchmark.

L’analyse ne devra pas retenir uniquement la stratégie offrant le rendement le plus élevé. La stabilité, le risque et le nombre de transactions devront également être étudiés.

---

## 13. Dashboard Streamlit

Le dashboard comportera les pages suivantes.

| Page | Contenu |
| --- | --- |
| Market Overview | Prix, variations, volatilité et tendances |
| Strategy Explorer | Choix de l’instrument, de la stratégie et des paramètres |
| Signals | Signaux, indicateurs techniques et justification |
| News Indicators | Pression des actualités, surprise et volume |
| Backtest | Equity curve, drawdown, transactions et métriques |
| Comparison | Comparaison des stratégies et benchmarks |
| Data Quality | Fraîcheur des données, erreurs et statut du pipeline |

Le dashboard devra permettre de comparer :

- la stratégie technique seule ;
- la stratégie technique enrichie par les flux RSS ;
- le Buy and Hold ;
- le benchmark global.

---

## 14. Structure du projet

```
projet_elt_commodities/
├── infrastructure/
│   ├── main.tf
│   ├── providers.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── bigquery.tf
│   └── iam.tf
├── scripts/
│   ├── extract_load/
│   │   ├── config.py
│   │   ├── ingest_commodities.py
│   │   ├── ingest_benchmarks.py
│   │   └── ingest_rss.py
│   ├── nlp/
│   │   ├── create_embeddings.py
│   │   ├── compute_relevance.py
│   │   └── compute_news_indicators.py
│   └── orchestrate.py
├── dbt_finance/
│   ├── models/
│   │   ├── landing/
│   │   ├── staging/
│   │   ├── warehouse/
│   │   └── marts/
│   ├── tests/
│   └── dbt_project.yml
├── backtesting/
│   ├── engine.py
│   ├── costs.py
│   ├── metrics.py
│   └── strategies/
│       ├── buy_and_hold.py
│       ├── moving_average.py
│       ├── moving_average_stoch_rsi.py
│       └── technical_news_filter.py
├── notebooks/
│   ├── 01_data_exploration.ipynb
│   ├── 02_indicator_validation.ipynb
│   ├── 03_news_indicator_analysis.ipynb
│   ├── 04_strategy_backtest.ipynb
│   └── 05_strategy_comparison.ipynb
├── dashboard/
│   ├── app.py
│   └── pages/
├── requirements/
│   └── requirements.txt
└── README.md
```

---

## 15. Planning prévisionnel

| Semaine | Jalons |
| --- | --- |
| S1 | Cadrage final, choix des instruments et initialisation du dépôt |
| S2 | Terraform, création des datasets BigQuery et configuration IAM |
| S3 | Ingestion des cours et des benchmarks |
| S4 | Ingestion RSS, nettoyage et déduplication |
| S5 | Modèles dbt Staging et tests qualité |
| S6 | Calcul des indicateurs techniques |
| S7 | Embeddings et indicateurs textuels |
| S8 | Développement du moteur de backtesting |
| S9 | Comparaison des stratégies et analyse hors échantillon |
| S10 | Dashboard Streamlit |
| S11 | Tests end-to-end, documentation et préparation de la soutenance |
| 07/07/2026 | Présentation finale et démonstration |

---

## 16. Risques principaux

| Risque | Impact | Mitigation |
| --- | --- | --- |
| Données Yahoo Finance indisponibles | Moyen | Retry, logs et conservation du dernier run valide |
| Futures difficiles à interpréter | Moyen | Documentation des contrats et effets de roulement |
| Articles peu pertinents | Moyen | Seuil de similarité et validation manuelle |
| Sentiment mal interprété | Moyen | Utilisation comme filtre et non comme signal autonome |
| Sur-optimisation des paramètres | Élevé | Découpage temporel et test hors échantillon |
| Faible performance des stratégies | Faible | Analyse transparente des résultats et des limites |
| Périmètre trop large | Élevé | Limitation du nombre d’instruments et de stratégies |
| Coûts Google Cloud | Faible | BigQuery serverless, vues dbt et suivi de la consommation |

---

## 17. Livrables

| Livrable | Description |
| --- | --- |
| Infrastructure Terraform | Ressources Google Cloud reproductibles |
| Pipeline ELT | Scripts d’ingestion automatisés et journalisés |
| Projet dbt | Transformations, documentation et tests |
| Indicateur textuel | Commodity News Pressure Index et indicateurs associés |
| Moteur de backtesting | Stratégies, coûts et métriques |
| Dashboard Streamlit | Visualisation interactive des résultats |
| Notebooks | Exploration, validation et comparaison |
| README | Architecture, installation et limites |
| Présentation finale | Slides et démonstration du dashboard |

---

## 18. Critères de réussite

Le projet sera considéré comme réussi si :

- l’infrastructure peut être créée avec Terraform ;
- les données sont ingérées automatiquement dans BigQuery ;
- les transformations dbt sont documentées et testées ;
- les indicateurs techniques et textuels sont reproductibles ;
- les stratégies sont exécutées sans fuite de données futures ;
- les frais sont intégrés au backtest ;
- les résultats sont comparés à des benchmarks ;
- le dashboard permet d’explorer les performances ;
- les limites du projet sont clairement documentées.

---

*Document de référence — Version 3.0 — Projet ELT Finance M1 Ynov 2025-2026*