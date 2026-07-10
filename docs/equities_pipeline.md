# Pipeline actions (équités)

Ce document décrit `scripts/extract_load/equities_trading.py`, une pipeline autonome de
backtesting sur un univers de 20 actions, adaptée de la pipeline matières premières du projet
(`scripts/extract_load/ingest_commodities.py`, `commodity_benchmark_index.py`,
`backtesting/`). Contrairement à la pipeline matières premières, elle ne dépend pas de
BigQuery ni de dbt : tout tourne en local à partir de yfinance.

---

## 1. Installation

```bash
python3.12 -m venv .venv
source .venv/bin/activate
make install
```

`matplotlib` a été ajouté à `requirements/requirements.txt` pour l'export des graphiques en
PNG sans interface graphique (ni `plotly` ni `streamlit`, déjà présents, ne le permettent sans
la dépendance additionnelle `kaleido`).

## 2. Lancer le script

```bash
python scripts/extract_load/equities_trading.py \
  --start 2015-01-01 --end 2026-01-01 --capital 10000 \
  --commission 0.001 --slippage 0.0005 --rebalance monthly

# Sous-ensemble de tickers
python scripts/extract_load/equities_trading.py --tickers AAPL NVDA ASML.AS

# Une seule stratégie
python scripts/extract_load/equities_trading.py --strategy breakout_20d

# ou via make
make equities
```

Toutes les options : `python scripts/extract_load/equities_trading.py --help`. Les valeurs
par défaut (capital, commissions, slippage, allocation, rebalancement, devise de référence,
plafond de position...) reprennent celles de `config/equities.yml`.

`--dry-run` valide l'univers et les tickers sans télécharger l'historique complet ni lancer de
backtest.

## 3. Modifier l'univers d'actions

L'univers est défini dans `config/equities.yml` (section `equities`), un ticker par entrée :

```yaml
- equity_id: AAPL
  ticker: AAPL
  name: Apple
  exchange: NASDAQ
  currency: USD
  enabled: true
```

Ajouter, retirer ou désactiver (`enabled: false`) un ticker n'importe où dans ce fichier. Le
benchmark de marché (`market_benchmark`) et les paramètres par défaut du portefeuille agrégé
(`portfolio`) sont dans le même fichier.

`--tickers` restreint une exécution à un sous-ensemble de cet univers ; un ticker absent de
`config/equities.yml` fait échouer la commande explicitement (aucune substitution silencieuse).

## 4. Choisir une stratégie

Le script réutilise les 5 stratégies déjà implémentées dans `backtesting/strategies/` :
`buy_and_hold`, `moving_average_cross`, `moving_average_stoch_rsi`, `technical_news_filter`,
`breakout_20d`. `--strategy all` (par défaut) les exécute toutes ; `--strategy <nom>` n'en
exécute qu'une (le Buy & Hold de comparaison est toujours calculé en plus).

`technical_news_filter` a été conçue pour un filtre d'actualités propre aux matières premières
(sentiment, risque géopolitique, choc d'offre). Aucune infrastructure NLP équivalente n'existe
pour les actions : les colonnes correspondantes sont absentes, et la classe les remplace alors
par une valeur neutre (0), ce qui désactive de fait le filtre d'actualités. La stratégie se
comporte donc comme un filtre technique pur (tendance + RSI) sur les actions — ceci est un
comportement documenté de la classe elle-même, pas une approximation ajoutée ici.

Les seuils de `moving_average_stoch_rsi` dans `config/strategies.yml` (0.2 / 0.8) sont exprimés
sur une échelle 0–1 alors que la classe attend une échelle 0–100 (comme `stochastic_rsi_k/d`) ;
ce script utilise donc les valeurs par défaut de la classe (20.0 / 80.0) plutôt que ce fichier,
pour ne pas neutraliser silencieusement le filtre. C'est un écart pré-existant dans le projet,
non spécifique aux actions.

## 5. Lire les résultats

Tout est exporté dans `outputs/equities/` :

| Fichier | Contenu |
| --- | --- |
| `ticker_validation.csv` | Résultat de la validation pré-téléchargement, ticker par ticker. |
| `data_quality_report.csv` | Doublons retirés, valeurs manquantes, prix incohérents corrigés, par ticker. |
| `cleaned_prices.csv` | OHLCV + prix ajusté + dividendes + splits, nettoyés. |
| `individual_backtests.csv` | Une ligne par (ticker, stratégie) : rendement, Sharpe, Sortino, Calmar, max drawdown, taux de réussite, nombre de trades, rendement moyen par trade, frais et slippage cumulés, exposition, turnover, `benchmark_outperformance` vs le Buy & Hold du même ticker. |
| `benchmark_results.csv` | Buy & Hold par action, portefeuille equal-weight (avec et sans effet de change), benchmark de marché. |
| `portfolio_results.csv` | Série quotidienne du portefeuille agrégé (`fx_adjusted` distingue la version convertie en devise de référence de la version "sans effet de change"). |
| `trades.csv` | Tous les ordres exécutés (prix d'exécution, frais, slippage, position résultante). |
| `equity_curves.csv` | Courbes de capital quotidiennes (stratégie, Buy & Hold, benchmark de marché). |
| `charts/*.png` | Graphiques (voir section 8). |
| `logs/` | Log détaillé de l'exécution + `pipeline_errors.csv` si des erreurs non bloquantes sont survenues. |

Les backtests individuels et le portefeuille agrégé sont exportés dans des fichiers séparés et
ne doivent pas être comparés terme à terme : le premier simule un capital indépendant par
ticker, le second un portefeuille unique réparti sur l'univers.

## 6. Méthodologie des benchmarks

- **Buy & Hold par action** : calculé sur le prix ajusté (`adjusted_close`) de chaque ticker,
  rebasé à 100 depuis sa propre première date disponible (pas depuis une date commune à tout
  l'univers).
- **Portefeuille equal-weight / inverse-vol** : réutilise
  `commodity_benchmark_index.build_synthetic_index` (déjà utilisé par les matières premières et
  `ingest_benchmarks.py`). Poids égaux ou inversement proportionnels à la volatilité glissante,
  rebalancement configurable (`--rebalance`), plafond de position configurable
  (`--max-position-weight`), nombre maximal de positions (`--max-positions`), réserve de cash
  (`--cash-reserve`, appliquée en réduisant le rendement investi par `(1 - cash_reserve)`, la
  part réservée ne rapportant rien). Sans levier, positions longues uniquement (aucune notion
  de vente à découvert dans une pondération equal-weight / inverse-vol).
- **Benchmark de marché** : Buy & Hold simple d'un ticker configurable (`--market-benchmark`,
  défaut `SPY`).
- **Biais du survivant** : l'univers de 20 tickers est fixé dans `config/equities.yml` et n'est
  pas reconstitué historiquement (composition actuelle projetée dans le passé). Un titre qui
  aurait fait faillite ou aurait été retiré de la cote sur la période testée n'apparaîtrait pas
  dans cet univers : les performances du portefeuille agrégé sont donc probablement optimistes
  par rapport à un portefeuille réellement investi à la date de début du backtest.

## 7. Dividendes, splits, frais et devises

- Les rendements et les backtests utilisent **le prix ajusté** (`adjusted_close`), pas le close
  brut : dividendes et splits sont donc reflétés dans la performance, pas seulement dans le
  signal. Les colonnes `dividends` et `stock_splits` brutes de yfinance sont conservées dans
  `cleaned_prices.csv` pour référence.
- Frais (`--commission`) et slippage (`--slippage`) sont appliqués à chaque exécution via
  `backtesting.costs.TransactionCostModel`, comme pour les matières premières.
- Chaque backtest individuel reste dans la devise locale du ticker (USD ou EUR). Le
  portefeuille agrégé convertit chaque série de prix vers une devise de référence
  (`--reference-currency`, défaut EUR) à l'aide de taux de change quotidiens récupérés via
  yfinance (paires `{DEVISE}{RÉFÉRENCE}=X`, ou la paire inverse si Yahoo ne liste qu'un sens).
  Un ticker dont le taux de change est indisponible est exclu du portefeuille agrégé (erreur
  journalisée dans `logs/pipeline_errors.csv`), jamais mélangé tel quel avec les autres devises.
- `benchmark_results.csv` fournit à la fois la version convertie en devise de référence
  (`equal_weight_portfolio`) et une version "sans effet de change"
  (`equal_weight_portfolio_no_fx`, moyenne simple des rendements locaux, sans conversion), pour
  isoler la contribution du change à la performance du portefeuille.

## 8. Graphiques

Générés avec matplotlib (backend `Agg`, sans serveur graphique) dans
`outputs/equities/charts/` : courbe stratégie vs Buy & Hold et drawdown par ticker, rendements
cumulés par action (base 100), performance et drawdown du portefeuille, heatmap de corrélation
des rendements quotidiens, nuage de points rendement/volatilité/drawdown, classement des
actions par Sharpe.

## 9. Limites de yfinance

- Historique parfois incomplet ou révisé rétroactivement (ajustements post-splits, dividendes
  spéciaux).
- Rate limiting possible sur de gros volumes de requêtes : le script télécharge un ticker à la
  fois (`--request-delay-seconds`, `--max-retries`) plutôt qu'en lot, comme
  `ingest_commodities.py`.
- Les places non américaines (Euronext Paris/Amsterdam ici) ont des calendriers de bourse et
  des fuseaux horaires différents de NASDAQ/NYSE : aucun forward-fill n'est appliqué pour
  combler ces écarts de calendrier dans les backtests individuels ; seul l'alignement du
  portefeuille agrégé tolère un report borné (`--max-forward-fill`) pour permettre un
  rebalancement multi-devises.

## 10. Risques de sur-apprentissage

Les paramètres des stratégies (fenêtres de moyennes mobiles, seuils RSI, etc.) sont ceux déjà
choisis pour les matières premières (`backtesting/strategies/*.py`) : ils n'ont pas été
recalibrés sur l'univers d'actions. De bonnes performances sur une fenêtre de test courte ou un
petit nombre de tickers (`--tickers`) peuvent ne pas se généraliser. `backtesting/validation.py`
(périodes calibration / validation / test) reste disponible pour évaluer une stratégie hors
échantillon avant de considérer un résultat comme robuste.

## 11. Backtest ≠ stratégie réellement exécutable

Ce backtest simule des ordres à la clôture du jour suivant le signal, avec un modèle de frais
et de slippage simplifié (taux constant, pas de carnet d'ordres, pas de limite de liquidité).
Il ne modélise pas : les contraintes de taille d'ordre réelles, la disponibilité du titre à
l'emprunt pour une position courte, les écarts bid/ask réels, les à-coups d'exécution en séance,
ni les frais de change réels appliqués par un courtier lors de la conversion de devises. Un
résultat positif en backtest ne garantit donc pas une performance équivalente en exécution
réelle.
