# Pédagogie — À quoi servent les fichiers `.yml` ?

Les fichiers `.yml` sont des fichiers de configuration.

Dans ce projet, ils servent à séparer :

- le code Python, qui exécute les traitements ;
- les paramètres du projet, qui peuvent changer sans modifier le code.

Autrement dit : le code décrit **comment faire**, les fichiers `.yml` décrivent **avec quoi travailler**.

---

## Pourquoi utiliser des `.yml` ?

Sans fichier `.yml`, il faudrait écrire les paramètres directement dans les scripts Python.

Exemple peu pratique :

```python
tickers = ["GC=F", "CL=F", "SI=F"]
start_date = "2020-01-01"
```

Le problème est que chaque changement oblige à modifier le code.

Avec un fichier `.yml`, les paramètres sont dans un fichier dédié :

```yaml
commodities:
  - symbol: GC=F
    name: Gold Futures
    category: precious_metals
```

Le script Python lit ce fichier, puis exécute le traitement.

---

## Avantages

- **Lisibilité** : les paramètres sont regroupés au même endroit.
- **Maintenance** : on peut ajouter un ticker sans toucher au code.
- **Réutilisation** : les mêmes scripts fonctionnent avec plusieurs configurations.
- **Sécurité** : les secrets restent dans `.env`, pas dans les `.yml`.
- **Clarté projet** : on comprend vite quelles données sont utilisées.

---

## Les fichiers `.yml` prévus dans le projet

Les fichiers de configuration seront placés dans :

```text
config/
```

Fichiers prévus :

```text
config/commodities.yml
config/benchmarks.yml
config/rss_sources.yml
config/strategies.yml
config/settings.yml
```

---

## `commodities.yml`

Ce fichier liste les matières premières étudiées.

Il répond aux questions :

- quelles matières premières suit-on ?
- quels tickers Yahoo Finance utilise-t-on ?
- dans quelle catégorie se trouve chaque instrument ?

Exemple :

```yaml
commodities:
  - symbol: GC=F
    name: Gold Futures
    category: precious_metals

  - symbol: CL=F
    name: Crude Oil WTI Futures
    category: energy
```

Utilisé par :

```text
scripts/extract_load/ingest_commodities.py
scripts/nlp/compute_relevance.py
dashboard/
```

---

## `benchmarks.yml`

Ce fichier définit les benchmarks utilisés pour comparer les stratégies.

Il répond aux questions :

- quel benchmark global utilise-t-on ?
- compare-t-on aussi chaque stratégie au Buy and Hold ?

Exemple :

```yaml
benchmarks:
  global:
    symbol: DBC
    name: Invesco DB Commodity Index Tracking Fund

  buy_and_hold:
    enabled: true
```

Utilisé par :

```text
scripts/extract_load/ingest_benchmarks.py
backtesting/
dbt_finance/
```

---

## `rss_sources.yml`

Ce fichier liste les flux RSS à récupérer.

Il répond aux questions :

- quelles sources d'actualités utilise-t-on ?
- quelle URL RSS faut-il appeler ?
- à quelle catégorie appartient la source ?

Exemple :

```yaml
rss_sources:
  - name: Investing Commodities
    url: https://example.com/rss/commodities
    category: commodities

  - name: Energy News
    url: https://example.com/rss/energy
    category: energy
```

Utilisé par :

```text
scripts/extract_load/ingest_rss.py
scripts/nlp/compute_news_indicators.py
```

---

## `strategies.yml`

Ce fichier définit les paramètres des stratégies de backtesting.

Il répond aux questions :

- quelles stratégies sont activées ?
- quelles fenêtres de moyennes mobiles utilise-t-on ?
- quels seuils RSI ou RSS applique-t-on ?
- quels frais et slippage utilise-t-on ?

Exemple :

```yaml
strategies:
  moving_average:
    enabled: true
    short_window: 20
    long_window: 50

  technical_news_filter:
    enabled: true
    short_window: 20
    long_window: 50
    news_pressure_threshold: 0
    novelty_threshold: 0.35
```

Utilisé par :

```text
backtesting/engine.py
backtesting/strategies/
dashboard/pages/04_strategy_explorer.py
```

---

## `settings.yml`

Ce fichier contient les paramètres généraux du pipeline.

Il répond aux questions :

- quelle date de début utiliser ?
- dans quel fuseau horaire tourne le pipeline ?
- où écrire les fichiers CSV temporaires ?
- quels datasets BigQuery utiliser ?

Exemple :

```yaml
pipeline:
  start_date: "2020-01-01"
  timezone: Europe/Paris

paths:
  market_data_raw: data/raw/market_data
  benchmarks_raw: data/raw/benchmarks
  news_raw: data/raw/news

bigquery:
  raw_dataset: raw
  dbt_dataset: dbt_finance
  mart_dataset: mart
```

Utilisé par :

```text
scripts/extract_load/config.py
scripts/orchestrate.py
scripts/extract_load/load_to_bigquery.py
```

---

## `.yml` ou `.env` : quelle différence ?

Les deux servent à configurer le projet, mais pas pour les mêmes choses.

| Fichier | Sert à stocker | Exemple |
| --- | --- | --- |
| `.yml` | paramètres métier ou techniques non secrets | tickers, sources RSS, fenêtres SMA |
| `.env` | variables locales et secrets | projet GCP, chemin credentials, clés API |

Règle simple :

- si l'information peut être partagée dans Git, elle peut aller dans un `.yml` ;
- si l'information est secrète ou propre à une machine, elle va dans `.env`.

---

## Exemple de flux avec un `.yml`

Exemple avec les matières premières :

```text
1. On ajoute GC=F dans config/commodities.yml.
2. scripts/extract_load/config.py lit le fichier YAML.
3. scripts/extract_load/ingest_commodities.py reçoit la liste des tickers.
4. Le script appelle Yahoo Finance pour chaque ticker.
5. Les données sont écrites en CSV dans data/raw/market_data/.
6. Le loader charge les données dans BigQuery.
```

Le code ne change pas si on ajoute une nouvelle matière première.

On modifie seulement :

```text
config/commodities.yml
```

---

## Résumé très court

Les fichiers `.yml` sont les tableaux de bord de configuration du projet.

Ils permettent de dire au pipeline :

- quelles données récupérer ;
- où les récupérer ;
- quels paramètres utiliser ;
- quelles stratégies exécuter ;
- où stocker les résultats.

Ils rendent le projet plus propre, plus facile à modifier et plus facile à expliquer.

