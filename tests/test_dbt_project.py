from pathlib import Path

import yaml


DBT_ROOT = Path("dbt_finance")


def test_dbt_project_core_files_exist() -> None:
    expected_files = [
        "dbt_project.yml",
        "packages.yml",
        "profiles.yml",
        "profiles.yml.example",
        "macros/generate_schema_name.sql",
        "models/sources.yml",
    ]

    for relative_path in expected_files:
        assert (DBT_ROOT / relative_path).exists()


def test_dbt_yaml_files_are_valid() -> None:
    for path in DBT_ROOT.rglob("*.yml"):
        if "target" in path.parts or "dbt_packages" in path.parts or not path.is_file():
            continue
        with path.open(encoding="utf-8") as file:
            assert yaml.safe_load(file) is not None


def test_dbt_expected_models_exist() -> None:
    expected_models = [
        "models/landing/landing_market_data.sql",
        "models/landing/landing_benchmarks.sql",
        "models/landing/landing_news.sql",
        "models/staging/stg_commodity_prices.sql",
        "models/staging/stg_benchmarks.sql",
        "models/staging/stg_news.sql",
        "models/staging/stg_pipeline_logs.sql",
        "models/warehouse/int_technical_indicators.sql",
        "models/warehouse/int_tradable_assets.sql",
        "models/warehouse/int_article_commodity_relevance.sql",
        "models/warehouse/int_commodity_news_features.sql",
        "models/warehouse/int_strategy_signals.sql",
        "models/warehouse/int_daily_returns.sql",
        "models/marts/mart_strategy_signals.sql",
        "models/marts/mart_backtest_trades.sql",
        "models/marts/mart_backtest_daily.sql",
        "models/marts/mart_strategy_metrics.sql",
        "models/marts/mart_dashboard_overview.sql",
        "models/marts/mart_validation_period_metrics.sql",
        "models/marts/mart_rss_filter_contribution.sql",
    ]

    for relative_path in expected_models:
        assert (DBT_ROOT / relative_path).exists()


def test_dbt_critical_tests_exist() -> None:
    expected_tests = [
        "tests/assert_ohlc_consistency.sql",
        "tests/assert_no_future_market_dates.sql",
        "tests/assert_fresh_market_data.sql",
        "tests/assert_valid_strategy_signals.sql",
        "tests/assert_no_duplicate_articles.sql",
        "tests/assert_technical_indicator_ranges.sql",
    ]

    for relative_path in expected_tests:
        assert (DBT_ROOT / relative_path).exists()


def test_dbt_backtest_marts_expose_step_12_metrics() -> None:
    metrics_sql = (DBT_ROOT / "models/marts/mart_strategy_metrics.sql").read_text(encoding="utf-8")
    daily_sql = (DBT_ROOT / "models/marts/mart_backtest_daily.sql").read_text(encoding="utf-8")
    trades_sql = (DBT_ROOT / "models/marts/mart_backtest_trades.sql").read_text(encoding="utf-8")
    returns_sql = (DBT_ROOT / "models/warehouse/int_daily_returns.sql").read_text(encoding="utf-8")

    expected_metrics = [
        "cumulative_return",
        "annualized_return",
        "annualized_volatility",
        "sharpe_ratio",
        "sortino_ratio",
        "max_drawdown",
        "calmar_ratio",
        "win_rate",
        "profit_factor",
        "trade_count",
        "avg_position_duration_days",
        "total_estimated_fees",
        "outperformance_vs_buy_hold",
        "outperformance_vs_global_benchmark",
    ]

    for metric in expected_metrics:
        assert metric in metrics_sql

    assert "net_strategy_return" in daily_sql
    assert "strategy_growth_factor" in daily_sql
    assert "greatest(1 + coalesce(net_strategy_return, 0), 0.000001)" in daily_sql
    assert "estimated_transaction_cost_rate" in trades_sql
    assert "coalesce(simple_return, 0)" in returns_sql


def test_dbt_stg_news_falls_back_when_published_at_is_missing() -> None:
    stg_news_sql = (DBT_ROOT / "models/staging/stg_news.sql").read_text(encoding="utf-8")

    assert "coalesce(" in stg_news_sql
    assert "cast(published_at as timestamp)" in stg_news_sql
    assert "cast(fetched_at as timestamp)" in stg_news_sql
    assert "cast(ingested_at as timestamp)" in stg_news_sql


def test_dbt_strategy_signals_materialize_all_spec_strategies() -> None:
    signals_sql = (DBT_ROOT / "models/warehouse/int_strategy_signals.sql").read_text(encoding="utf-8")

    expected_strategies = [
        "buy_and_hold",
        "moving_average_cross",
        "moving_average_stoch_rsi",
        "technical_news_filter",
        "breakout_20d",
    ]

    for strategy_name in expected_strategies:
        assert strategy_name in signals_sql

    assert "union all" in signals_sql
    assert "previous_high_20d" in signals_sql
    assert "previous_low_10d" in signals_sql
    assert "last_breakout_entry_date" in signals_sql
    assert "last_breakout_exit_date" in signals_sql


def test_dbt_tradable_assets_include_synthetic_index() -> None:
    tradable_assets_sql = (DBT_ROOT / "models/warehouse/int_tradable_assets.sql").read_text(encoding="utf-8")
    indicators_sql = (DBT_ROOT / "models/warehouse/int_technical_indicators.sql").read_text(encoding="utf-8")

    assert "synthetic_commodity_index" in tradable_assets_sql
    assert "'COMMODITY_INDEX' as symbol" in tradable_assets_sql
    assert "group by date" in tradable_assets_sql
    assert "ref('int_tradable_assets')" in indicators_sql


def test_dbt_technical_news_filter_uses_nlp_thresholds() -> None:
    signals_sql = (DBT_ROOT / "models/warehouse/int_strategy_signals.sql").read_text(encoding="utf-8")

    expected_conditions = [
        "weighted_sentiment_score >= -0.15",
        "geopolitical_risk_score < 0.75",
        "supply_shock_score < 0.75",
    ]

    for condition in expected_conditions:
        assert condition in signals_sql


def test_dbt_validation_marts_expose_step_13_controls() -> None:
    validation_sql = (DBT_ROOT / "models/marts/mart_validation_period_metrics.sql").read_text(encoding="utf-8")
    rss_sql = (DBT_ROOT / "models/marts/mart_rss_filter_contribution.sql").read_text(encoding="utf-8")

    expected_controls = [
        "calibration",
        "validation",
        "test",
        "is_optimization_allowed",
        "robust_selection_score",
    ]

    for control in expected_controls:
        assert control in validation_sql

    assert "rss_adds_value" in rss_sql
    assert "technical_news_filter" in rss_sql
    assert "moving_average_cross" in rss_sql
    assert "period_strategy_growth_factor" in validation_sql
    assert "greatest(1 + coalesce(net_strategy_return, 0), 0.000001)" in validation_sql


def test_dbt_schema_macro_aligns_marts_with_terraform_dataset() -> None:
    macro = (DBT_ROOT / "macros/generate_schema_name.sql").read_text(encoding="utf-8")

    assert "custom_schema_name == 'marts'" in macro
    assert "var('mart_dataset', 'mart')" in macro
    assert "target.schema" in macro
