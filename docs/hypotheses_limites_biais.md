# Hypothèses, limites et biais évités

Ce document explicite les hypothèses méthodologiques du projet.

---

## 1. Hypothèses principales

```text
Les prix Yahoo Finance sont utilisés comme séries de recherche.
Les contrats futures continus Yahoo simplifient le roll réel.
Le benchmark synthétique est une référence interne, pas un indice investissable officiel.
COMMODITY_INDEX est une version backtestable de ce benchmark synthétique.
Les coûts dbt sont estimés en taux.
Le moteur Python calcule des frais monétaires sur portefeuille simulé.
Le sentiment NLP est utilisé comme filtre, pas comme vérité absolue.
```

---

## 2. Biais évités

### Look-ahead bias

Règle :

```text
Un signal calculé à J est exécuté à J+1.
```

Implémentation :

```text
int_daily_returns décale le signal avec lag(signal, 1, 0).
BacktestEngine décale les signaux avec shift(1).
```

### Sur-optimisation

Découpage :

```text
2020-2023 : calibration
2024      : validation
2025-J-1  : test final
```

La période de test final ne doit pas servir au choix des paramètres.

### Survivorship/data leakage

Le projet documente l'univers d'actifs dans `config/commodities.yml`.

Toute modification d'univers doit être justifiée.

---

## 3. Limites

```text
Les données de marché peuvent contenir des trous ou ajustements Yahoo Finance.
Les flux RSS ne couvrent pas tout l'univers informationnel.
FinBERT peut mal interpréter certains textes spécialisés commodities.
Les embeddings légers sont un compromis performance/coût.
Les frais réels dépendent du courtier, du contrat et de la liquidité.
Le slippage est simplifié.
COMMODITY_INDEX simplifie la réplication réelle d'un panier de futures.
Le dashboard dépend de BigQuery et de la fraîcheur des marts.
```

---

## 4. Interprétation des résultats

Une stratégie n'est pas retenue uniquement parce qu'elle maximise le rendement brut.

Elle doit être évaluée selon :

```text
rendement cumulé ;
Sharpe ;
Sortino ;
drawdown ;
stabilité par instrument ;
nombre de transactions ;
surperformance vs Buy and Hold ;
surperformance vs benchmark global ;
comportement sur COMMODITY_INDEX ;
apport réel du filtre RSS.
```
