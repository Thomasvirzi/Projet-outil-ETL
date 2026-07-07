from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard.services.backtest_dashboard import EXPECTED_STRATEGY_NAMES
from dashboard.services.data_loader import (
    load_rss_contribution,
    load_strategy_metrics,
    load_validation_metrics,
    safe_load,
)
from dashboard.services.filters import dataframe_to_csv, unique_values


def _format_percent_columns(dataframe: pd.DataFrame) -> dict[str, object]:
    return {
        column: st.column_config.NumberColumn(column, format="%.2%")
        for column in [
            "cumulative_return",
            "annualized_return",
            "annualized_volatility",
            "max_drawdown",
            "win_rate",
            "outperformance_vs_buy_hold",
            "outperformance_vs_global_benchmark",
            "return_delta",
            "sharpe_delta",
            "drawdown_delta",
        ]
        if column in dataframe
    }


def _filter_metrics(
    metrics: pd.DataFrame,
    symbols: list[str],
    strategies: list[str],
) -> pd.DataFrame:
    filtered = metrics.copy()
    if symbols and "symbol" in filtered:
        filtered = filtered[filtered["symbol"].isin(symbols)]
    if strategies and "strategy_name" in filtered:
        filtered = filtered[filtered["strategy_name"].isin(strategies)]
    return filtered


def _prepare_comparison_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    prepared = dataframe.copy()
    numeric_columns = [
        "cumulative_return",
        "annualized_return",
        "annualized_volatility",
        "sharpe_ratio",
        "max_drawdown",
        "win_rate",
        "outperformance_vs_buy_hold",
        "outperformance_vs_global_benchmark",
        "trade_count",
    ]
    for column in numeric_columns:
        if column in prepared:
            prepared[column] = pd.to_numeric(prepared[column], errors="coerce").astype(
                "float64"
            )

    if "trade_count" in prepared:
        prepared["plotly_trade_count_size"] = prepared["trade_count"].fillna(0).clip(
            lower=0
        )
        max_trade_count = prepared["plotly_trade_count_size"].max()
        if pd.isna(max_trade_count) or max_trade_count == 0:
            prepared["plotly_trade_count_size"] = 1.0

    return prepared


def render_comparison_dashboard() -> None:
    st.title("Comparaison des stratégies")
    st.caption(
        "Compare les stratégies sur tous les actifs : rendement, risque, drawdown, "
        "activité de trading et robustesse par période."
    )

    metrics, metrics_error = safe_load(load_strategy_metrics)
    validation, validation_error = safe_load(load_validation_metrics)
    rss, rss_error = safe_load(load_rss_contribution)

    if metrics_error:
        st.error(metrics_error)
        st.stop()
    if validation_error:
        st.warning("Les métriques de validation ne sont pas disponibles.")
    if rss_error:
        st.warning("La comparaison technique vs filtre RSS n'est pas disponible.")

    if metrics.empty:
        st.info("Aucune métrique de stratégie disponible. Lance `make dbt-run`.")
        st.stop()

    available_strategies = unique_values(metrics, "strategy_name")
    missing_strategies = [
        strategy_name
        for strategy_name in EXPECTED_STRATEGY_NAMES
        if strategy_name not in available_strategies
    ]
    ordered_strategies = [
        strategy_name
        for strategy_name in EXPECTED_STRATEGY_NAMES
        if strategy_name in available_strategies
    ]
    ordered_strategies.extend(
        strategy_name
        for strategy_name in available_strategies
        if strategy_name not in ordered_strategies
    )
    if missing_strategies:
        st.warning(
            "Certaines stratégies attendues ne sont pas présentes dans `mart_strategy_metrics` : "
            f"{', '.join(missing_strategies)}. Lance `make dbt-run`, puis rafraîchis le dashboard.",
            icon="⚠️",
        )

    with st.sidebar:
        st.header("Filtres comparaison")
        symbols = st.multiselect(
            "Actifs",
            unique_values(metrics, "symbol"),
            default=unique_values(metrics, "symbol"),
        )
        strategies = st.multiselect(
            "Stratégies",
            ordered_strategies,
            default=ordered_strategies,
        )

    filtered = _prepare_comparison_dataframe(_filter_metrics(metrics, symbols, strategies))
    if filtered.empty:
        st.info("Aucune métrique ne correspond aux filtres sélectionnés.")
        st.stop()

    summary = (
        filtered.groupby("strategy_name", as_index=False)
        .agg(
            avg_cumulative_return=("cumulative_return", "mean"),
            avg_sharpe_ratio=("sharpe_ratio", "mean"),
            avg_max_drawdown=("max_drawdown", "mean"),
            tested_assets=("symbol", "nunique"),
            total_trades=("trade_count", "sum"),
            avg_outperformance_vs_buy_hold=("outperformance_vs_buy_hold", "mean"),
            avg_outperformance_vs_global_benchmark=(
                "outperformance_vs_global_benchmark",
                "mean",
            ),
        )
        .sort_values("avg_cumulative_return", ascending=False)
    )

    kpi_cols = st.columns(4)
    best_return = summary.iloc[0]
    best_sharpe = summary.sort_values("avg_sharpe_ratio", ascending=False).iloc[0]
    kpi_cols[0].metric("Stratégies", filtered["strategy_name"].nunique())
    kpi_cols[1].metric("Actifs testés", filtered["symbol"].nunique())
    kpi_cols[2].metric("Meilleur rendement moyen", best_return["strategy_name"])
    kpi_cols[3].metric("Meilleur Sharpe moyen", best_sharpe["strategy_name"])

    chart_col, risk_col = st.columns(2)
    with chart_col:
        st.plotly_chart(
            px.bar(
                summary,
                x="strategy_name",
                y="avg_cumulative_return",
                color="strategy_name",
                title="Rendement moyen par stratégie",
                labels={
                    "strategy_name": "Stratégie",
                    "avg_cumulative_return": "Rendement moyen",
                },
            ),
            use_container_width=True,
        )
    with risk_col:
        st.plotly_chart(
            px.scatter(
                filtered,
                x="annualized_volatility",
                y="cumulative_return",
                color="strategy_name",
                symbol="symbol",
                size=(
                    "plotly_trade_count_size"
                    if "plotly_trade_count_size" in filtered
                    else None
                ),
                title="Couple rendement / risque",
                labels={
                    "annualized_volatility": "Volatilité annualisée",
                    "cumulative_return": "Rendement cumulé",
                    "strategy_name": "Stratégie",
                    "plotly_trade_count_size": "Trades",
                },
            ),
            use_container_width=True,
        )

    strategy_tab, validation_tab, rss_tab = st.tabs(
        ["Synthèse stratégies", "Validation temporelle", "Apport RSS"]
    )

    with strategy_tab:
        st.dataframe(
            summary,
            use_container_width=True,
            hide_index=True,
            column_config=_format_percent_columns(summary),
        )
        st.dataframe(
            filtered.sort_values(["strategy_name", "symbol"]),
            use_container_width=True,
            hide_index=True,
            column_config=_format_percent_columns(filtered),
        )
        st.download_button(
            "Exporter les métriques CSV",
            dataframe_to_csv(filtered),
            "strategy_comparison.csv",
            "text/csv",
        )

    with validation_tab:
        validation_filtered = _filter_metrics(validation, symbols, strategies)
        if validation_filtered.empty:
            st.info("Aucune donnée de validation disponible pour cette sélection.")
        else:
            st.plotly_chart(
                px.bar(
                    validation_filtered,
                    x="strategy_name",
                    y="robust_selection_score",
                    color="validation_period",
                    barmode="group",
                    title="Score de robustesse par période",
                ),
                use_container_width=True,
            )
            st.dataframe(
                validation_filtered,
                use_container_width=True,
                hide_index=True,
                column_config=_format_percent_columns(validation_filtered),
            )

    with rss_tab:
        rss_filtered = rss.copy()
        if symbols and "symbol" in rss_filtered:
            rss_filtered = rss_filtered[rss_filtered["symbol"].isin(symbols)]
        if rss_filtered.empty:
            st.info("Aucune comparaison RSS disponible pour cette sélection.")
        else:
            st.plotly_chart(
                px.bar(
                    rss_filtered,
                    x="symbol",
                    y="return_delta",
                    color="validation_period",
                    title="Delta rendement : technique + RSS vs technique seule",
                ),
                use_container_width=True,
            )
            st.dataframe(
                rss_filtered,
                use_container_width=True,
                hide_index=True,
                column_config=_format_percent_columns(rss_filtered),
            )
