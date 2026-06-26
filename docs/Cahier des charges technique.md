# Cahier des charges technique

## Plateforme ELT et backtesting sur les matières premières

**Projet :** ELT Commodities & Backtesting

**Cadre :** M1 Ynov Data & IA — 2025-2026

**Présentation finale :** 7 juillet 2026

**Version :** 1.0

---

## 1. Objectif technique

Concevoir une architecture capable de :

- collecter quotidiennement des données de marché et des flux RSS ;
- stocker les données brutes dans Google BigQuery ;
- transformer les données avec dbt ;
- générer des embeddings et des indicateurs textuels ;
- calculer des indicateurs techniques ;
- exécuter des stratégies de backtesting ;
- exposer les résultats dans un dashboard Streamlit ;
- provisionner l’infrastructure avec Terraform.

L’ensemble doit être reproductible, testable, documenté et exécutable localement.

---

## 2. Architecture générale

```
Sources externes
├── Yahoo Finance
└── Flux RSS financiers
        │
        ▼
Scripts Python d’ingestion
        │
        ▼
BigQuery — raw
        │
        ▼
Traitements NLP et modèles dbt
        │
        ▼
BigQuery — dbt_finance / mart
        │
        ├── Moteur de backtesting
        └── Dashboard Streamlit
```

Terraform assure la création et la configuration des ressources Google Cloud.

---

## 3. Stack technique

| Domaine | Technologie |
| --- | --- |
| Langage principal | Python 3.11 ou version compatible |
| Infrastructure as Code | Terraform |
| Cloud | Google Cloud Platform |
| Data warehouse | Google BigQuery |
| Transformations | dbt Core + dbt-bigquery |
| Données de marché | `yfinance` |
| Flux RSS | `feedparser` |
| Nettoyage HTML | `BeautifulSoup` |
| Embeddings | `sentence-transformers` |
| Sentiment | FinBERT ou modèle financier équivalent |
| Data processing | Pandas, NumPy |
| Indicateurs financiers | `pandas-ta`, `ta` ou calculs internes |
| Backtesting | Moteur Python interne |
| Dashboard | Streamlit |
| Orchestration | APScheduler |
| Tests | Pytest + tests dbt |
| Versionnement | Git |
| Configuration | Variables d’environnement et fichiers YAML |

---

## 4. Infrastructure Google Cloud

### 4.1 Ressources provisionnées avec Terraform

Terraform devra créer ou configurer :

- les API Google Cloud nécessaires ;
- les datasets BigQuery ;
- le service account du pipeline ;
- les rôles IAM ;
- éventuellement un bucket Cloud Storage ;
- les paramètres de localisation ;
- les outputs utiles au déploiement.

### 4.2 Datasets BigQuery

| Dataset | Usage |
| --- | --- |
| `raw` | Données brutes issues des sources |
| `dbt_finance` | Modèles Landing, Staging et Warehouse |
| `mart` | Tables finales utilisées par les backtests et Streamlit |

### 4.3 Structure Terraform

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

### 4.4 Contraintes

- aucun identifiant sensible ne doit être écrit dans le code ;
- les permissions IAM doivent suivre le principe du moindre privilège ;
- les datasets doivent utiliser une localisation unique ;
- Terraform doit pouvoir être exécuté avec `plan`, `apply` et `destroy`.

---

## 5. Ingestion des données

## 5.1 Données de marché

Le module `ingest_commodities.py` devra :

- récupérer les données journalières OHLCV ;
- charger l’historique depuis le 1er janvier 2020 ;
- effectuer une mise à jour incrémentale ;
- normaliser les dates et les types ;
- détecter les doublons ;
- charger les données dans `raw.market_data_raw`.

### Schéma minimal

```
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

### Gestion des erreurs

- trois tentatives maximum ;
- backoff exponentiel ;
- journalisation des erreurs ;
- absence de doublons lors d’une relance ;
- conservation du dernier état valide.

---

## 5.2 Benchmarks

Le module `ingest_benchmarks.py` devra récupérer :

- les données Buy and Hold de chaque instrument ;
- les données d’un benchmark global ;
- les mêmes champs et fréquences que les actifs étudiés.

---

## 5.3 Flux RSS

Le module `ingest_rss.py` devra :

- lire les URLs configurées ;
- récupérer le titre, la date, la source, l’URL et le contenu disponible ;
- nettoyer le HTML ;
- normaliser l’encodage ;
- calculer un hash ;
- charger les données dans `raw.news_raw`.

### Schéma minimal

```
article_id
title
source
url
published_at
clean_text
content_hash
ingested_at
```

---

## 6. Traitements NLP

## 6.1 Génération des embeddings

Le module `create_embeddings.py` devra :

- charger un modèle Sentence Transformers ;
- générer un vecteur pour chaque article ;
- enregistrer le nom et la version du modèle ;
- éviter de recalculer les embeddings existants ;
- journaliser les erreurs.

### Schéma minimal

```
article_id
embedding
embedding_model
embedding_version
created_at
```

---

## 6.2 Association article–matière première

Le module `compute_relevance.py` devra :

- créer une description de référence par matière première ;
- générer ou charger son embedding ;
- calculer la similarité cosinus avec chaque article ;
- appliquer un seuil configurable ;
- autoriser plusieurs associations par article.

### Sortie

```
article_id
commodity_symbol
similarity_score
is_relevant
calculated_at
```

---

## 6.3 Sentiment et nouveauté

Le pipeline devra calculer :

- `positive_probability` ;
- `negative_probability` ;
- `neutral_probability` ;
- `sentiment_score` ;
- `novelty_score`.

Le score de sentiment recommandé est :

```
sentiment_score = positive_probability - negative_probability
```

La nouveauté pourra être obtenue en comparant chaque article aux articles récents avec une fenêtre configurable.

---

## 6.4 Indicateurs textuels

Les traitements devront produire quotidiennement :

```
commodity_symbol
date
news_pressure_score
news_surprise_20d
news_volume
news_acceleration
novelty_score
sentiment_dispersion
geopolitical_risk_score
supply_shock_score
weather_risk_score
```

Les indicateurs thématiques pourront être optionnels dans le MVP.

---

## 7. Transformations dbt

## 7.1 Organisation

```
dbt_finance/
├── models/
│   ├── landing/
│   ├── staging/
│   ├── warehouse/
│   └── marts/
├── macros/
├── tests/
├── dbt_project.yml
└── packages.yml
```

## 7.2 Modèles attendus

### Landing

- vues directes sur les tables `raw` ;
- aucune logique métier complexe.

### Staging

- `stg_commodity_prices`
- `stg_benchmarks`
- `stg_news`
- `stg_pipeline_logs`

Traitements :

- renommage des colonnes ;
- cast des types ;
- déduplication ;
- contrôle des valeurs ;
- ajout de flags qualité.

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

---

## 7.3 Matérialisation

| Couche | Matérialisation |
| --- | --- |
| Landing | `view` |
| Staging | `view` |
| Warehouse | `view` ou `incremental` |
| Marts | `table` ou `incremental` |

---

## 7.4 Tests dbt

Les tests doivent couvrir :

- `not_null` ;
- `unique` ;
- `accepted_values` ;
- relations entre tables ;
- unicité du couple symbole-date ;
- cohérence OHLC ;
- fraîcheur des données ;
- absence de dates futures ;
- validité des signaux.

---

## 8. Indicateurs financiers

Le module de calcul devra produire au minimum :

- SMA 20 ;
- SMA 50 ;
- RSI 14 ;
- Stochastic RSI K ;
- Stochastic RSI D ;
- MACD ;
- signal MACD ;
- ATR 14 ;
- volatilité historique ;
- rendement simple ;
- rendement logarithmique.

Les fenêtres et seuils doivent être configurables.

Aucun calcul ne doit utiliser de donnée future.

---

## 9. Moteur de backtesting

## 9.1 Structure

```
backtesting/
├── engine.py
├── portfolio.py
├── costs.py
├── metrics.py
├── models.py
└── strategies/
    ├── base.py
    ├── buy_and_hold.py
    ├── moving_average.py
    ├── moving_average_stoch_rsi.py
    └── technical_news_filter.py
```

## 9.2 Stratégies minimales

Le moteur devra intégrer :

- Buy and Hold ;
- croisement de moyennes mobiles ;
- moyennes mobiles avec Stochastic RSI ;
- stratégie technique avec filtre RSS.

Chaque stratégie devra hériter d’une interface commune.

Exemple :

```python
class Strategy:
    def generate_signals(self, data):
        raise NotImplementedError
```

---

## 9.3 Règles d’exécution

Le moteur devra respecter les contraintes suivantes :

- signal calculé à la clôture de J ;
- exécution au plus tôt à l’ouverture de J+1 ;
- une seule position par instrument dans le MVP ;
- absence de vente à découvert ;
- prise en compte des frais ;
- prise en compte optionnelle du slippage ;
- capital initial configurable ;
- absence de look-ahead bias.

---

## 9.4 Données produites

### Transactions

```
backtest_id
strategy_id
symbol
entry_date
entry_price
exit_date
exit_price
gross_return
fees
net_return
holding_period
exit_reason
```

### Portefeuille journalier

```
backtest_id
date
cash
position_value
portfolio_value
daily_return
drawdown
exposure
```

---

## 9.5 Métriques

Le module `metrics.py` devra calculer :

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
- surperformance par rapport au benchmark.

---

## 10. Dashboard Streamlit

## 10.1 Structure

```
dashboard/
├── app.py
├── pages/
│   ├── 01_market_overview.py
│   ├── 02_indicators.py
│   ├── 03_news_indicators.py
│   ├── 04_strategy_explorer.py
│   ├── 05_backtest.py
│   ├── 06_comparison.py
│   └── 07_data_quality.py
└── services/
    ├── bigquery_client.py
    └── data_loader.py
```

## 10.2 Fonctions attendues

Le dashboard devra permettre de :

- choisir un instrument ;
- filtrer par catégorie et période ;
- afficher les indicateurs techniques ;
- afficher les indicateurs textuels ;
- consulter les signaux ;
- lancer ou consulter un backtest ;
- comparer plusieurs stratégies ;
- exporter les résultats au format CSV ;
- afficher le statut du pipeline.

---

## 10.3 Contraintes d’interface

- interface responsive ;
- navigation simple ;
- chargement des données mis en cache ;
- gestion claire des erreurs ;
- affichage des paramètres du backtest ;
- affichage d’un avertissement sur les risques financiers.

---

## 11. Orchestration

APScheduler devra exécuter les tâches dans l’ordre suivant :

1. ingestion des données de marché ;
2. ingestion des benchmarks ;
3. ingestion RSS ;
4. génération des embeddings ;
5. calcul des scores textuels ;
6. exécution de `dbt run` ;
7. exécution de `dbt test` ;
8. mise à jour des backtests ;
9. écriture du statut final.

Chaque tâche devra produire un log contenant :

```
run_id
task_name
start_time
end_time
status
rows_processed
error_message
```

---

## 12. Configuration

Les paramètres doivent être centralisés.

```
config/
├── commodities.yml
├── benchmarks.yml
├── rss_sources.yml
├── strategies.yml
└── settings.yml
```

Les secrets devront être stockés dans :

- des variables d’environnement ;
- un fichier `.env` ignoré par Git ;
- ou un mécanisme Google Cloud adapté.

Aucun secret ne doit être commité.

---

## 13. Sécurité

Les exigences minimales sont :

- authentification par service account ;
- permissions BigQuery limitées ;
- séparation entre développement et production si possible ;
- chiffrement natif Google Cloud ;
- journalisation des accès et erreurs ;
- exclusion des fichiers sensibles du dépôt Git.

---

## 14. Tests

## 14.1 Tests unitaires

Pytest devra couvrir :

- calcul des indicateurs ;
- règles de signaux ;
- calcul des frais ;
- calcul des métriques ;
- déduplication ;
- score de sentiment ;
- similarité article–matière première.

## 14.2 Tests d’intégration

Ils devront vérifier :

- ingestion vers BigQuery ;
- exécution dbt ;
- lecture depuis Streamlit ;
- exécution complète d’un backtest ;
- cohérence entre les tables Marts et le dashboard.

## 14.3 Tests end-to-end

Un scénario complet devra couvrir :

```
Source externe
→ ingestion
→ stockage raw
→ transformations
→ calcul des signaux
→ backtest
→ affichage Streamlit
```

---

## 15. Performance

Les objectifs indicatifs sont :

| Traitement | Objectif |
| --- | --- |
| Ingestion marché | moins de 10 minutes |
| Ingestion RSS | moins de 10 minutes |
| Embeddings quotidiens | moins de 30 minutes |
| dbt run + test | moins de 15 minutes |
| Backtest unitaire | moins de 10 secondes |
| Chargement d’une page Streamlit | moins de 5 secondes avec cache |

Ces valeurs constituent des objectifs de projet et non des engagements de production.

---

## 16. Gestion des coûts

Les mesures suivantes devront être appliquées :

- utilisation du free tier BigQuery ;
- partitionnement des tables par date ;
- clustering par symbole lorsque pertinent ;
- requêtes limitées aux colonnes utiles ;
- modèles intermédiaires en vues ;
- cache Streamlit ;
- absence de réservation BigQuery dédiée ;
- suivi de la consommation cloud.

---

## 17. Arborescence cible

```
projet_elt_commodities/
├── infrastructure/
├── config/
├── scripts/
│   ├── extract_load/
│   ├── nlp/
│   └── orchestrate.py
├── dbt_finance/
├── backtesting/
├── dashboard/
├── notebooks/
├── tests/
├── requirements/
├── .env.example
├── .gitignore
├── Makefile
└── README.md
```

---

## 18. Commandes attendues

Le projet devra proposer des commandes simples.

```bash
make infra-plan
make infra-apply
make ingest
make dbt-run
make dbt-test
make backtest
make dashboard
make test
```

À défaut de `Makefile`, les commandes équivalentes devront être documentées dans le README.

---

## 19. Critères de validation technique

Le projet sera techniquement validé si :

- Terraform crée les ressources Google Cloud attendues ;
- les données sont chargées dans BigQuery sans doublons ;
- les modèles dbt s’exécutent avec succès ;
- les tests critiques passent ;
- les embeddings sont générés et historisés ;
- les indicateurs techniques et textuels sont reproductibles ;
- les backtests respectent la temporalité ;
- les frais sont intégrés ;
- Streamlit lit les données depuis les tables Marts ;
- les erreurs du pipeline sont journalisées ;
- le projet peut être installé avec le README ;
- aucun secret n’est présent dans le dépôt.

---

## 20. Livrables techniques

- fichiers Terraform ;
- scripts Python d’ingestion ;
- pipeline NLP ;
- projet dbt ;
- moteur de backtesting ;
- dashboard Streamlit ;
- suite de tests ;
- fichiers de configuration ;
- documentation d’installation ;
- documentation d’architecture ;
- schéma des données ;
- README d’exploitation.

---

*Document de référence — Cahier des charges technique — Version 1.0*