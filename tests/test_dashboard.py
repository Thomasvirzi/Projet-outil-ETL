from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import pytest

from dashboard.comparison_page import _prepare_comparison_dataframe
from dashboard.services.bigquery_client import BigQueryConnectionError, BigQuerySettings, format_bigquery_error
from dashboard.services.backtest_dashboard import (
    BacktestSelection,
    build_portfolio_curves,
    compute_curve_metrics,
    filter_backtest_inputs,
)
from dashboard.services.data_loader import build_date_filter, sql_string_literal
from dashboard.services.filters import dataframe_to_csv, filter_dataframe, unique_values


DASHBOARD_ROOT = Path("dashboard")


def test_dashboard_expected_files_exist() -> None:
    expected_files = [
        "app.py",
        "backtest_page.py",
        "comparison_page.py",
        "services/backtest_dashboard.py",
        "services/bigquery_client.py",
        "services/data_loader.py",
    ]

    for relative_path in expected_files:
        assert (DASHBOARD_ROOT / relative_path).exists()


def test_dashboard_product_keeps_only_backtest_and_comparison_tools() -> None:
    page_files = sorted((DASHBOARD_ROOT / "pages").glob("*.py"))
    app = (DASHBOARD_ROOT / "app.py").read_text(encoding="utf-8")

    assert page_files == []
    assert '["Backtest", "Comparaison"]' in app
    assert "render_backtest_dashboard" in app
    assert "render_comparison_dashboard" in app


def test_make_dashboard_sets_pythonpath() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "PYTHONPATH=$(CURDIR) streamlit run dashboard/app.py" in makefile
    assert "--server.address=$(STREAMLIT_ADDRESS)" in makefile
    assert "--server.port=$(STREAMLIT_PORT)" in makefile
    assert "--browser.serverAddress=$(STREAMLIT_ADDRESS)" in makefile


def test_makefile_uses_active_python_not_external_python_env() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "PYTHON := $(shell command -v python 2>/dev/null || command -v python3)" in makefile
    assert "PIP := $(PYTHON) -m pip" in makefile


def test_makefile_exposes_nlp_targets() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "nlp: check-python" in makefile
    assert "$(PYTHON) scripts/orchestrate.py --only nlp" in makefile
    assert "nlp-mock:" in makefile
    assert "scripts/nlp/create_embeddings.py --mock-embeddings" in makefile
    assert "scripts/nlp/compute_sentiment.py --mock-sentiment" in makefile


def test_bigquery_settings_require_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCP_PROJECT", raising=False)

    with pytest.raises(BigQueryConnectionError):
        BigQuerySettings.from_env(env_file=tmp_path / "missing.env")


def test_bigquery_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    monkeypatch.setenv("BIGQUERY_MARTS_DATASET", "demo_marts")

    settings = BigQuerySettings.from_env()

    assert settings.project_id == "demo-project"
    assert settings.marts_dataset == "demo_marts"


def test_bigquery_settings_support_legacy_mart_dataset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    monkeypatch.delenv("BIGQUERY_MARTS_DATASET", raising=False)
    monkeypatch.setenv("BIGQUERY_MART_DATASET", "mart")

    settings = BigQuerySettings.from_env()

    assert settings.marts_dataset == "mart"


def test_bigquery_settings_defaults_match_terraform_datasets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    monkeypatch.delenv("BIGQUERY_MARTS_DATASET", raising=False)
    monkeypatch.delenv("BIGQUERY_MART_DATASET", raising=False)
    monkeypatch.delenv("BIGQUERY_STAGING_DATASET", raising=False)
    monkeypatch.delenv("BIGQUERY_DBT_DATASET", raising=False)

    settings = BigQuerySettings.from_env()

    assert settings.marts_dataset == "mart"
    assert settings.staging_dataset == "dbt_finance"


def test_bigquery_missing_mart_error_explains_dbt_step() -> None:
    message = format_bigquery_error(
        RuntimeError("404 Not found: Table demo:mart.mart_dashboard_overview was not found in location EU")
    )

    assert "L'infrastructure Terraform crée seulement les datasets" in message
    assert "`make dbt-run`" in message


def test_build_date_filter_handles_optional_bounds() -> None:
    assert build_date_filter("date", None, None) == "1 = 1"
    assert build_date_filter("date", date(2026, 1, 1), date(2026, 1, 31)) == (
        "date >= DATE '2026-01-01' and date <= DATE '2026-01-31'"
    )


def test_sql_string_literal_escapes_quotes() -> None:
    assert sql_string_literal("GC=F") == "'GC=F'"
    assert sql_string_literal("O'Reilly") == "'O''Reilly'"


def test_filter_dataframe_and_csv_export() -> None:
    dataframe = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02"],
            "symbol": ["GC=F", "CL=F"],
            "category": ["metal", "energy"],
            "strategy_name": ["buy_and_hold", "technical_news_filter"],
        }
    )

    filtered = filter_dataframe(dataframe, symbol="GC=F", category="metal")

    assert len(filtered) == 1
    assert unique_values(dataframe, "symbol") == ["CL=F", "GC=F"]
    assert dataframe_to_csv(filtered).startswith(b"date,symbol")


def test_backtest_dashboard_filters_and_rebases_portfolio_curves() -> None:
    daily = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02", "2026-01-01", "2026-01-02"],
            "symbol": ["GC=F", "GC=F", "CL=F", "CL=F"],
            "strategy_name": ["technical_news_filter"] * 4,
            "net_strategy_return": [0.10, -0.05, 0.20, 0.10],
            "asset_return": [0.05, 0.05, 0.01, 0.01],
        }
    )
    trades = pd.DataFrame(
        {
            "trade_date": ["2026-01-01", "2026-01-02"],
            "symbol": ["GC=F", "CL=F"],
            "strategy_name": ["technical_news_filter", "technical_news_filter"],
        }
    )
    benchmark = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02"],
            "benchmark_name": ["Synthetic Commodity Index", "Synthetic Commodity Index"],
            "daily_return": [0.02, 0.03],
        }
    )
    selection = BacktestSelection(
        symbol="GC=F",
        strategy_names=["technical_news_filter"],
        initial_capital=100_000,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
    )

    filtered_daily, filtered_trades, filtered_benchmark = filter_backtest_inputs(
        daily,
        trades,
        benchmark,
        selection,
    )
    curves = build_portfolio_curves(filtered_daily, filtered_benchmark, 100_000)
    metrics = compute_curve_metrics(curves, filtered_trades)

    assert filtered_daily["symbol"].eq("GC=F").all()
    assert filtered_trades["symbol"].eq("GC=F").all()
    assert set(curves["series_type"]) == {"strategy", "buy_hold", "benchmark"}
    strategy_metric = metrics[metrics["series_name"] == "technical_news_filter"].iloc[0]
    assert round(strategy_metric["final_equity"], 2) == 104_500
    assert round(strategy_metric["cumulative_return"], 3) == 0.045
    assert strategy_metric["trade_count"] == 1


def test_buy_and_hold_strategy_has_zero_outperformance_vs_buy_hold_baseline() -> None:
    daily = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02"],
            "symbol": ["BZ=F", "BZ=F"],
            "strategy_name": ["buy_and_hold", "buy_and_hold"],
            "net_strategy_return": [0.0, 0.04189],
            "asset_return": [0.0, 0.04350],
        }
    )

    curves = build_portfolio_curves(
        daily=daily,
        benchmark=pd.DataFrame(),
        initial_capital=100_000,
        buy_hold_daily=daily,
    )
    metrics = compute_curve_metrics(curves)
    buy_hold_strategy = metrics[
        (metrics["series_name"] == "buy_and_hold")
        & (metrics["series_type"] == "strategy")
    ].iloc[0]

    assert round(buy_hold_strategy["cumulative_return"], 5) == 0.04189
    assert buy_hold_strategy["outperformance_vs_buy_hold"] == 0


def test_comparison_plotly_dataframe_converts_nullable_trade_count() -> None:
    dataframe = pd.DataFrame(
        {
            "strategy_name": ["technical_news_filter"],
            "symbol": ["GC=F"],
            "annualized_volatility": pd.Series([0.12], dtype="Float64"),
            "cumulative_return": pd.Series([0.08], dtype="Float64"),
            "trade_count": pd.Series([32], dtype="Int64"),
        }
    )

    prepared = _prepare_comparison_dataframe(dataframe)
    figure = px.scatter(
        prepared,
        x="annualized_volatility",
        y="cumulative_return",
        color="strategy_name",
        symbol="symbol",
        size="plotly_trade_count_size",
    )

    assert prepared["plotly_trade_count_size"].dtype == "float64"
    assert figure.data
