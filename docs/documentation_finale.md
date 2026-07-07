# Documentation finale

Ce fichier sert d'index de documentation pour la soutenance et la reprise du projet.

---

## Installation et architecture

- `init.md` — procédure chronologique complète pour reconstruire le projet depuis `make infra-destroy` jusqu'au dashboard.
- `docs/installation_locale.md` — installation locale, variables d'environnement, lancement pipeline/dbt/dashboard.
- `docs/config_terraform_GCP.md` — configuration Terraform et BigQuery sur Google Cloud.
- `docs/architecture_globale.md` — vue d'ensemble des composants et datasets.
- `docs/schema_base_donnees.md` — documentation technique du schéma BigQuery avec diagrammes Mermaid.
- `docs/flux_donnee.md` — trajet détaillé des données, des sources aux marts.

---

## Backtesting, stratégies et interprétation métier

- `docs/strategies_backtesting.md` — description métier détaillée des stratégies, baselines, index et métriques.
- `docs/hypotheses_limites_biais.md` — hypothèses méthodologiques, limites, biais évités et lecture des résultats.

---

## Dashboard et soutenance

- `docs/soutenance_slides.md` — plan de slides recommandé.

---

## Tables finales principales

Les résultats opérationnels à présenter viennent principalement de :

```text
mart.mart_strategy_signals
mart.mart_backtest_daily
mart.mart_backtest_trades
mart.mart_strategy_metrics
mart.mart_validation_period_metrics
mart.mart_rss_filter_contribution
```

Le dashboard Streamlit est volontairement recentré sur deux usages :

```text
Backtest
Comparaison
```
