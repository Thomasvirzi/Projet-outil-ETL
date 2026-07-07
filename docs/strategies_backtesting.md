# Stratégies de backtesting — Lecture métier

Ce document explique les stratégies de backtesting du projet, non seulement d'un point de vue technique, mais surtout du point de vue métier : quelle hypothèse de marché chaque stratégie teste, ce qu'elle doit prouver, comment interpréter ses résultats, et quelles limites garder en tête.

Le dashboard Streamlit permet de tester ces stratégies sur chaque matière première et sur l'actif synthétique `COMMODITY_INDEX`, qui représente l'indice interne construit à partir du panier de commodities du projet.

---

## 1. Cadre commun du backtest

Toutes les stratégies suivent les mêmes règles méthodologiques.

| Règle | Choix projet | Pourquoi c'est important |
| --- | --- | --- |
| Type de position | Long ou flat uniquement | Le MVP évite la vente à découvert et reste interprétable. |
| Signal | `1` = long, `0` = flat | Représentation simple et comparable entre stratégies. |
| Exécution | Signal calculé à J, exécuté à J+1 | Évite le look-ahead bias : on ne trade pas une information pas encore disponible. |
| Coûts | Frais + slippage | Une stratégie active doit battre les coûts qu'elle génère. |
| Comparaison | Buy & Hold net, index commodities, métriques de risque | On ne juge pas une stratégie uniquement au rendement brut. |

Les signaux sont matérialisés dans dbt :

```text
dbt_finance.models.warehouse.int_strategy_signals
```

Les performances finales sont exposées dans :

```text
mart.mart_backtest_daily
mart.mart_backtest_trades
mart.mart_strategy_metrics
mart.mart_validation_period_metrics
mart.mart_rss_filter_contribution
```

---

## 2. Univers backtestable

Le projet ne teste pas uniquement les matières premières individuelles. Il expose aussi l'indice synthétique comme un actif backtestable.

| Type d'actif | Exemple | Source | Usage métier |
| --- | --- | --- | --- |
| Matière première | `GC=F`, `BZ=F`, `CL=F` | `raw.market_data_raw` puis `stg_commodity_prices` | Tester une stratégie sur un marché précis. |
| Indice synthétique | `COMMODITY_INDEX` | `raw.benchmarks_raw` puis `stg_benchmarks` | Tester une stratégie sur le panier commodities global du projet. |

Le modèle dbt qui crée cet univers est :

```text
dbt_finance/models/warehouse/int_tradable_assets.sql
```

`COMMODITY_INDEX` est construit depuis le benchmark `synthetic_commodity_index`. Il est agrégé à une ligne par date, puis traité comme un actif avec un prix `close = benchmark_level`.

Lecture métier :

```text
Tester une stratégie sur COMMODITY_INDEX revient à demander :
"Cette règle fonctionne-t-elle sur le marché commodities diversifié du projet,
et pas seulement sur un contrat isolé ?"
```

---

## 3. Stratégie 1 — Buy and Hold

Fichier Python :

```text
backtesting/strategies/buy_and_hold.py
```

Nom dbt/dashboard :

```text
buy_and_hold
```

### Hypothèse métier

Le marché étudié monte suffisamment sur la période pour qu'une détention passive soit pertinente.

Cette stratégie ne cherche pas à anticiper les retournements. Elle sert de baseline minimale : si une stratégie active ne bat pas Buy & Hold après frais et slippage, son utilité métier est faible.

### Règle de signal

```text
signal = 1 tous les jours
```

### Ce qu'elle mesure

| Élément | Interprétation |
| --- | --- |
| Performance Buy & Hold | Rendement passif de l'actif sur la période. |
| Drawdown | Risque subi par un investisseur passif. |
| Trade count | Devrait être très faible : entrée initiale puis conservation. |
| Écart vs Buy & Hold | Doit être 0 quand la stratégie sélectionnée est elle-même `buy_and_hold`. |

### Point important dashboard

Le dashboard compare désormais les stratégies au Buy & Hold net, c'est-à-dire avec la même logique d'exécution J+1 et de coûts. On évite ainsi de comparer une stratégie nette à une baseline brute.

---

## 4. Stratégie 2 — Croisement de moyennes mobiles

Fichier Python :

```text
backtesting/strategies/moving_average.py
```

Nom dbt/dashboard :

```text
moving_average_cross
```

### Hypothèse métier

Les matières premières ont parfois des phases de tendance. Quand la moyenne courte passe au-dessus de la moyenne longue, le marché est considéré comme orienté positivement.

Cette stratégie teste une logique de tendance simple, lisible et défendable.

### Règle de signal

```text
long si sma_20 >= sma_50
flat sinon
```

### Lecture métier

| Cas | Décision | Interprétation |
| --- | --- | --- |
| `sma_20 >= sma_50` | Long | La tendance récente confirme la tendance moyenne. |
| `sma_20 < sma_50` | Flat | Le marché est jugé insuffisamment porteur. |

### Forces

- Simple à expliquer.
- Peu dépendante de paramètres complexes.
- Sert de stratégie technique seule de référence.

### Limites

- Réagit avec retard lors des retournements.
- Peut multiplier les faux signaux en marché latéral.
- Ne tient pas compte de la surchauffe ou du contexte news.

---

## 5. Stratégie 3 — SMA + Stochastic RSI

Fichier Python :

```text
backtesting/strategies/moving_average_stoch_rsi.py
```

Nom dbt/dashboard :

```text
moving_average_stoch_rsi
```

### Hypothèse métier

Une tendance positive est plus intéressante si le momentum confirme l'entrée sans être déjà excessivement surchauffé.

Cette stratégie ajoute un filtre de timing à la stratégie de tendance.

### Conditions par défaut

```text
sma_20 >= sma_50
stochastic_rsi_k >= 20
stochastic_rsi_d <= 80
```

### Lecture métier

| Condition | Rôle |
| --- | --- |
| `sma_20 >= sma_50` | Vérifie que la tendance est positive. |
| `stochastic_rsi_k >= 20` | Évite d'acheter un momentum trop faible. |
| `stochastic_rsi_d <= 80` | Évite d'acheter un actif déjà trop surchauffé. |

### Ce qu'elle doit prouver

Elle doit idéalement réduire les entrées tardives ou trop agressives par rapport à `moving_average_cross`, tout en conservant une performance comparable.

### Limites

- Plus de paramètres signifie plus de risque d'optimisation excessive.
- Peut rater de fortes tendances si le filtre momentum est trop strict.

---

## 6. Stratégie 4 — Technique + filtre RSS/NLP

Fichier Python :

```text
backtesting/strategies/technical_news_filter.py
```

Nom dbt/dashboard :

```text
technical_news_filter
```

### Hypothèse métier

Une stratégie technique peut être améliorée si l'on évite d'acheter lorsque les actualités contredisent le signal de marché.

Exemple métier : un actif est techniquement haussier, mais les flux RSS indiquent un risque géopolitique ou un choc d'offre élevé. La stratégie peut alors rester flat.

### Conditions techniques

```text
close > sma_20
sma_20 >= sma_50
rsi_14 entre 30 et 75
```

### Conditions news/NLP

```text
weighted_sentiment_score >= -0.15
geopolitical_risk_score < 0.75
supply_shock_score < 0.75
```

### Signification des variables NLP

| Variable | Interprétation métier | Source logique |
| --- | --- | --- |
| `weighted_sentiment_score` | Sentiment agrégé des articles pertinents, pondéré par pertinence, source, fraîcheur et nouveauté. | Sentiment + pertinence article/commodity + pondération. |
| `geopolitical_risk_score` | Intensité des thèmes géopolitiques dans les articles pertinents. | Détection thématique dans `compute_news_indicators.py`. |
| `supply_shock_score` | Intensité des thèmes liés aux ruptures d'offre, stocks, production, export/import. | Détection thématique dans `compute_news_indicators.py`. |

Important : `geopolitical_risk_score` et `supply_shock_score` ne sont pas des embeddings bruts. Ce sont des features métier construites à partir des textes, puis agrégées par jour et par commodity.

### Lecture métier des seuils

| Condition | Décision implicite |
| --- | --- |
| `weighted_sentiment_score < -0.15` | Le sentiment est trop négatif pour valider une entrée long. |
| `geopolitical_risk_score >= 0.75` | Le risque géopolitique est jugé trop élevé. |
| `supply_shock_score >= 0.75` | Le risque de choc d'offre est jugé trop élevé. |

### Ce qu'elle doit prouver

Cette stratégie doit être comparée à une stratégie technique sans RSS, notamment `moving_average_cross`.

La question métier n'est pas :

```text
Est-ce que la stratégie RSS fait toujours mieux ?
```

La vraie question est :

```text
Est-ce que le filtre RSS réduit certains mauvais trades, améliore le drawdown,
ou améliore la robustesse hors échantillon ?
```

### Point d'attention actuel

Les variables NLP fonctionnent et sont présentes dans les marts après reconstruction dbt. Cependant, il est possible que, sur une période donnée, aucune date ne combine à la fois :

```text
signal technique positif
+
news défavorable au-delà des seuils
```

Dans ce cas, la stratégie fonctionne correctement mais ne bloque aucun trade. Il faut alors lire `mart_rss_filter_contribution` pour mesurer si l'apport RSS est réellement visible.

---

## 7. Stratégie 5 — Breakout 20 jours

Fichier Python :

```text
backtesting/strategies/breakout.py
```

Nom dbt/dashboard :

```text
breakout_20d
```

### Hypothèse métier

Un dépassement du plus haut récent peut signaler une accélération de tendance.

Cette stratégie teste une logique de momentum pur : acheter quand le marché casse une résistance récente.

### Règle de signal

```text
entrée long si close > plus haut précédent sur 20 jours
maintien long tant qu'aucun signal de sortie n'apparaît
sortie si close < plus bas précédent sur 10 jours
```

Le calcul utilise les seuils précédents, pas les seuils incluant le jour courant, afin d'éviter le look-ahead bias.

Cette version est volontairement une logique de position, pas un simple signal événementiel. Une cassure de résistance déclenche l'entrée, puis la position reste ouverte jusqu'à invalidation de tendance. Sans cette logique de maintien, la stratégie entrerait et sortirait trop souvent, ce qui détruirait la performance avec les frais.

### Forces

- Capture les mouvements impulsifs.
- Très lisible métier : franchissement de résistance.
- Complémentaire aux moyennes mobiles.

### Limites

- Peut acheter tard après une forte hausse.
- Sensible aux faux breakouts.
- Le choix du seuil de sortie influence fortement le turnover.

---

## 8. Comment comparer les stratégies

La comparaison doit se faire avec plusieurs axes.

| Axe | Pourquoi |
| --- | --- |
| Rendement cumulé | Mesure le gain final. |
| Sharpe | Compare rendement et volatilité. |
| Sortino | Se concentre davantage sur la volatilité négative. |
| Max drawdown | Mesure la perte maximale depuis un plus haut. |
| Calmar | Relie rendement annualisé et drawdown. |
| Trade count | Vérifie si la performance vient d'une activité excessive. |
| Écart vs Buy & Hold | Mesure l'intérêt d'être actif plutôt que passif. |
| Écart vs index | Mesure l'intérêt face au marché commodities diversifié. |
| Robustesse validation/test | Vérifie que la stratégie n'est pas seulement bonne en calibration. |

Une stratégie métier intéressante n'est pas forcément celle avec le meilleur rendement brut. Elle doit aussi être lisible, stable, peu fragile aux paramètres, et robuste hors échantillon.

---

## 9. Lecture recommandée dans le dashboard

Dans le Backtest Lab :

1. choisir un actif ou `COMMODITY_INDEX` ;
2. sélectionner plusieurs stratégies ;
3. fixer le capital initial ;
4. choisir la période ;
5. comparer la courbe portefeuille, le drawdown, les trades et les métriques.

Dans l'onglet Comparaison :

1. comparer les stratégies sur tous les actifs ;
2. regarder rendement moyen et Sharpe moyen ;
3. vérifier la robustesse par période ;
4. inspecter l'apport RSS via `mart_rss_filter_contribution`.

---

## 10. Résumé métier

| Stratégie | Question métier |
| --- | --- |
| `buy_and_hold` | Est-ce qu'une détention passive suffit ? |
| `moving_average_cross` | Une tendance simple est-elle exploitable ? |
| `moving_average_stoch_rsi` | Le momentum améliore-t-il le timing d'entrée ? |
| `technical_news_filter` | Les news RSS/NLP évitent-elles certains mauvais signaux techniques ? |
| `breakout_20d` | Les cassures de prix récentes capturent-elles les accélérations ? |
| `COMMODITY_INDEX` comme actif | Les stratégies fonctionnent-elles sur un panier diversifié, pas seulement sur un contrat isolé ? |
