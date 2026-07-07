# Slides de soutenance — Plan proposé

Ce fichier sert de support pour créer les slides finales.

Durée cible : 10 à 12 minutes.

---

## Slide 1 — Titre

```text
Plateforme ELT et backtesting sur les matières premières
M1 Data & IA — Ynov
```

Message :

```text
Construire une chaîne complète de collecte, transformation, analyse NLP, backtesting et visualisation.
```

---

## Slide 2 — Problématique

Question :

```text
Les actualités financières améliorent-elles une stratégie technique sur commodities ?
```

Points :

```text
marchés volatils ;
news géopolitiques et supply shocks ;
besoin d'un pipeline reproductible.
```

---

## Slide 3 — Architecture globale

Schéma :

```text
Yahoo/RSS → Python → BigQuery raw → NLP/dbt → marts → backtesting/Streamlit
```

Insister sur :

```text
ELT ;
BigQuery ;
dbt ;
Streamlit ;
orchestration quotidienne.
```

---

## Slide 4 — Ingestion

Contenu :

```text
Yahoo Finance OHLCV ;
benchmarks Buy and Hold + synthetic index ;
RSS financiers ;
déduplication ;
chargement raw BigQuery.
```

---

## Slide 5 — NLP

Contenu :

```text
embeddings ;
similarité article-matière première ;
FinBERT/sentiment ;
novelty ;
news_pressure_score ;
risques géopolitique/offre/météo.
```

---

## Slide 6 — dbt et qualité

Contenu :

```text
landing ;
staging ;
warehouse ;
marts ;
tests dbt critiques ;
partitionnement / clustering.
```

---

## Slide 7 — Indicateurs et stratégies

Indicateurs :

```text
SMA ;
RSI ;
Stochastic RSI ;
MACD ;
ATR ;
volatilité ;
Bollinger.
```

Stratégies :

```text
Buy and Hold ;
SMA cross ;
SMA + Stoch RSI ;
Technique + filtre RSS ;
Breakout 20 jours.
```

Univers testé :

```text
matières premières individuelles ;
COMMODITY_INDEX comme actif synthétique backtestable.
```

---

## Slide 8 — Backtesting et biais évités

Contenu :

```text
exécution J+1 ;
frais ;
slippage ;
pas de short MVP ;
split 2020-2023 / 2024 / 2025-J-1.
```

---

## Slide 9 — Dashboard Streamlit Backtest Lab

Outils :

```text
Backtest ;
Comparaison.
```

Message :

```text
Le dashboard n'est pas un portail généraliste : il sert à simuler un portefeuille,
comparer plusieurs stratégies et vérifier les baselines Buy & Hold / index.
```

---

## Slide 10 — Tests, sécurité et orchestration

Contenu :

```text
89 tests ;
audit secrets ;
CI GitHub Actions ;
APScheduler ;
logs pipeline ;
contrôle coûts BigQuery.
```

---

## Slide 11 — Résultats attendus et lecture métier

Expliquer :

```text
comparer stratégie technique seule vs filtre RSS ;
tester les stratégies sur COMMODITY_INDEX ;
ne pas sélectionner au rendement brut ;
regarder Sharpe, drawdown, stabilité, transactions.
```

---

## Slide 12 — Limites et perspectives

Limites :

```text
futures continus Yahoo ;
RSS incomplets ;
NLP perfectible ;
coûts/slippage simplifiés.
```

Perspectives :

```text
déploiement cloud complet ;
meilleur modèle thématique ;
mode offline dashboard ;
monitoring coûts/performance.
```
