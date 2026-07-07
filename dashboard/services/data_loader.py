from __future__ import annotations

from datetime import date

import pandas as pd

from dashboard.services.bigquery_client import BigQueryClient, BigQueryConnectionError

try:
    import streamlit as st
except ImportError:  # pragma: no cover - exercised when Streamlit is absent locally.
    st = None


def _cache_data(ttl: int = 900):
    if st is None:
        def decorator(function):
            return function

        return decorator

    return st.cache_data(ttl=ttl, show_spinner=False)


def empty_dataframe() -> pd.DataFrame:
    return pd.DataFrame()


MART_COLUMNS = {
    "mart_dashboard_overview": [
        "commodity_id",
        "commodity_name",
        "symbol",
        "category",
        "latest_date",
        "latest_close",
        "latest_signal",
        "news_volume",
        "news_pressure_score",
        "weighted_sentiment_score",
        "strategy_name",
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
        "avg_exposure",
    ],
    "mart_strategy_metrics": [
        "strategy_name",
        "symbol",
        "commodity_id",
        "commodity_name",
        "start_date",
        "end_date",
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
        "total_estimated_transaction_cost_rate",
        "outperformance_vs_buy_hold",
        "outperformance_vs_global_benchmark",
    ],
    "mart_validation_period_metrics": [
        "validation_period",
        "is_optimization_allowed",
        "strategy_name",
        "symbol",
        "commodity_id",
        "commodity_name",
        "start_date",
        "end_date",
        "cumulative_return",
        "sharpe_ratio",
        "max_drawdown",
        "trade_count",
        "robust_selection_score",
    ],
    "mart_rss_filter_contribution": [
        "validation_period",
        "symbol",
        "commodity_id",
        "commodity_name",
        "return_delta",
        "sharpe_delta",
        "drawdown_delta",
        "rss_adds_value",
    ],
}


def build_date_filter(date_column: str, start_date: date | None, end_date: date | None) -> str:
    filters = []
    if start_date is not None:
        filters.append(f"{date_column} >= DATE '{start_date.isoformat()}'")
    if end_date is not None:
        filters.append(f"{date_column} <= DATE '{end_date.isoformat()}'")
    return " and ".join(filters) if filters else "1 = 1"


def sql_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@_cache_data(ttl=900)
def load_table(table_name: str, limit: int = 5_000) -> pd.DataFrame:
    client = BigQueryClient()
    columns = MART_COLUMNS.get(table_name, ["*"])
    selected_columns = ", ".join(columns)
    query = f"""
        select {selected_columns}
        from {client.table_id(table_name)}
        limit {int(limit)}
    """
    return client.query_dataframe(query)


@_cache_data(ttl=900)
def load_market_overview() -> pd.DataFrame:
    return load_table("mart_dashboard_overview", limit=10_000)


@_cache_data(ttl=900)
def load_strategy_signals(symbol: str | None = None, start_date: date | None = None, end_date: date | None = None) -> pd.DataFrame:
    client = BigQueryClient()
    filters = [build_date_filter("date", start_date, end_date)]
    if symbol:
        filters.append(f"symbol = {sql_string_literal(symbol)}")

    query = f"""
        select *
        from {client.table_id('mart_strategy_signals')}
        where {' and '.join(filters)}
        order by symbol, date
    """
    return client.query_dataframe(query)


@_cache_data(ttl=900)
def load_backtest_daily(
    symbol: str | None = None,
    strategy_name: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    client = BigQueryClient()
    filters = [build_date_filter("date", start_date, end_date)]
    if symbol:
        filters.append(f"symbol = {sql_string_literal(symbol)}")
    if strategy_name:
        filters.append(f"strategy_name = {sql_string_literal(strategy_name)}")
    where_clause = " and ".join(filters) if filters else "1 = 1"

    query = f"""
        select
            commodity_id,
            commodity_name,
            symbol,
            category,
            strategy_name,
            date,
            close,
            asset_return,
            signal,
            executed_position,
            strategy_return,
            previous_position,
            estimated_transaction_cost_rate,
            estimated_fee,
            estimated_slippage,
            net_strategy_return,
            cumulative_strategy_return,
            cumulative_asset_return,
            cumulative_estimated_transaction_cost_rate
        from {client.table_id('mart_backtest_daily')}
        where {where_clause}
        order by strategy_name, symbol, date
    """
    return client.query_dataframe(query)


@_cache_data(ttl=900)
def load_backtest_trades(
    symbol: str | None = None,
    strategy_name: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    client = BigQueryClient()
    filters = [build_date_filter("trade_date", start_date, end_date)]
    if symbol:
        filters.append(f"symbol = {sql_string_literal(symbol)}")
    if strategy_name:
        filters.append(f"strategy_name = {sql_string_literal(strategy_name)}")
    where_clause = " and ".join(filters) if filters else "1 = 1"

    query = f"""
        select
            commodity_id,
            commodity_name,
            symbol,
            strategy_name,
            trade_date,
            trade_price,
            previous_position,
            executed_position,
            position_delta,
            estimated_transaction_cost_rate,
            estimated_fee,
            estimated_slippage,
            trade_type
        from {client.table_id('mart_backtest_trades')}
        where {where_clause}
        order by strategy_name, symbol, trade_date
    """
    return client.query_dataframe(query)


@_cache_data(ttl=900)
def load_global_benchmark(
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    client = BigQueryClient()
    query = f"""
        select
            date,
            benchmark_id,
            benchmark_type,
            benchmark_name,
            benchmark_level,
            daily_return
        from {client.table_id('stg_benchmarks', dataset=client.settings.staging_dataset)}
        where {build_date_filter("date", start_date, end_date)}
          and (
            component_id is null
            or benchmark_type in ('synthetic', 'synthetic_index', 'global')
            or benchmark_id in ('synthetic_commodity_index', 'global_commodities')
          )
        qualify row_number() over (
            partition by date
            order by
                case
                    when benchmark_id = 'synthetic_commodity_index' then 1
                    when component_id is null then 2
                    else 3
                end,
                benchmark_id
        ) = 1
        order by date
    """
    return client.query_dataframe(query)


@_cache_data(ttl=900)
def load_strategy_metrics() -> pd.DataFrame:
    return load_table("mart_strategy_metrics", limit=10_000)


@_cache_data(ttl=900)
def load_validation_metrics() -> pd.DataFrame:
    return load_table("mart_validation_period_metrics", limit=10_000)


@_cache_data(ttl=900)
def load_rss_contribution() -> pd.DataFrame:
    return load_table("mart_rss_filter_contribution", limit=10_000)


@_cache_data(ttl=900)
def load_pipeline_logs() -> pd.DataFrame:
    client = BigQueryClient()
    query = f"""
        select *
        from {client.table_id('stg_pipeline_logs', dataset=client.settings.staging_dataset)}
        order by started_at desc
        limit 5000
    """
    return client.query_dataframe(query)


def safe_load(loader, *args, **kwargs) -> tuple[pd.DataFrame, str | None]:
    try:
        return loader(*args, **kwargs), None
    except BigQueryConnectionError as exc:
        return empty_dataframe(), str(exc)
    except Exception as exc:
        return empty_dataframe(), f"Unexpected loading error: {exc}"
