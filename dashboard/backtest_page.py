from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard.services.backtest_dashboard import (
    BacktestSelection,
    EXPECTED_STRATEGY_NAMES,
    build_portfolio_curves,
    compute_curve_metrics,
    filter_backtest_inputs,
    format_percentage,
    normalize_date_column,
)
from dashboard.services.data_loader import (
    load_backtest_daily,
    load_backtest_trades,
    load_global_benchmark,
    load_strategy_metrics,
    safe_load,
)
from dashboard.services.filters import dataframe_to_csv, unique_values


def _coerce_period(value: object, default_start: date, default_end: date) -> tuple[date, date]:
    if isinstance(value, tuple) and len(value) == 2:
        start_date, end_date = value
        return start_date or default_start, end_date or default_end
    return default_start, default_end


def _format_currency(value: float) -> str:
    return f"{value:,.0f} €".replace(",", " ")


def _format_number(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def _display_metric_cards(metrics: pd.DataFrame) -> None:
    strategy_metrics = metrics[metrics["series_type"] == "strategy"].copy()
    if strategy_metrics.empty:
        st.info("Aucune métrique de stratégie disponible pour cette sélection.")
        return

    selected = strategy_metrics.sort_values("final_equity", ascending=False).iloc[0]
    cols = st.columns(5)
    cols[0].metric("Capital final", _format_currency(selected["final_equity"]))
    cols[1].metric("Performance", format_percentage(selected["cumulative_return"]))
    cols[2].metric("Sharpe", _format_number(selected["sharpe_ratio"]))
    cols[3].metric("Max drawdown", format_percentage(selected["max_drawdown"]))
    cols[4].metric("Trades", int(selected["trade_count"]))

    comparison_cols = st.columns(2)
    comparison_cols[0].metric(
        "Écart vs Buy & Hold",
        format_percentage(selected["outperformance_vs_buy_hold"]),
    )
    comparison_cols[1].metric(
        "Écart vs index",
        format_percentage(selected["outperformance_vs_index"]),
    )


def _display_curves(curves: pd.DataFrame) -> None:
    if curves.empty:
        st.info("Aucune courbe portefeuille disponible pour cette sélection.")
        return

    fig = px.line(
        curves.sort_values("date"),
        x="date",
        y="equity",
        color="series_name",
        line_dash="series_type",
        labels={
            "date": "Date",
            "equity": "Valeur du portefeuille",
            "series_name": "Série",
            "series_type": "Type",
        },
        title="Évolution du portefeuille",
    )
    fig.update_layout(legend_title_text="", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)


def _display_drawdown(curves: pd.DataFrame) -> None:
    if curves.empty:
        return

    drawdowns = curves.sort_values("date").copy()
    drawdowns["peak"] = drawdowns.groupby("series_name")["equity"].cummax()
    drawdowns["drawdown"] = drawdowns["equity"] / drawdowns["peak"] - 1
    fig = px.area(
        drawdowns,
        x="date",
        y="drawdown",
        color="series_name",
        labels={"drawdown": "Drawdown", "date": "Date", "series_name": "Série"},
        title="Drawdown par série",
    )
    fig.update_layout(legend_title_text="", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)


def render_backtest_dashboard() -> None:
    st.title("Backtest de stratégies commodities")
    st.caption(
        "Choisis un actif, une ou plusieurs stratégies, un capital initial et une période. "
        "Le résultat est comparé au Buy & Hold de l'actif et à l'index commodities."
    )

    st.warning(
        "Outil pédagogique : les performances historiques ne constituent pas un conseil financier.",
        icon="⚠️",
    )

    universe, universe_error = safe_load(load_strategy_metrics)

    if universe_error:
        st.error(universe_error)
        st.stop()

    universe = normalize_date_column(universe, "start_date")
    universe = normalize_date_column(universe, "end_date")
    if universe.empty:
        st.info("Aucune métrique de backtest disponible. Lance `make dbt-build` après l'ingestion.")
        st.stop()

    symbols = unique_values(universe, "symbol")
    available_strategies = unique_values(universe, "strategy_name")
    strategies = [
        strategy_name
        for strategy_name in EXPECTED_STRATEGY_NAMES
        if strategy_name in available_strategies
    ]
    strategies.extend(
        strategy_name
        for strategy_name in available_strategies
        if strategy_name not in strategies
    )
    missing_strategies = [
        strategy_name
        for strategy_name in EXPECTED_STRATEGY_NAMES
        if strategy_name not in available_strategies
    ]
    min_date = universe["start_date"].min()
    max_date = universe["end_date"].max()

    if missing_strategies:
        st.warning(
            "Certaines stratégies attendues ne sont pas présentes dans les marts BigQuery : "
            f"{', '.join(missing_strategies)}. Lance `make dbt-run`, puis clique sur "
            "`Rafraîchir les données` ou redémarre `make dashboard`.",
            icon="⚠️",
        )

    with st.sidebar:
        st.header("Paramètres du backtest")
        if st.button("Rafraîchir les données"):
            st.cache_data.clear()
            st.rerun()

        symbol = st.selectbox("Actif", symbols)
        selected_strategies = st.multiselect(
            "Stratégies",
            strategies,
            default=strategies[: min(2, len(strategies))],
        )
        initial_capital = st.number_input(
            "Capital initial",
            min_value=1_000.0,
            max_value=100_000_000.0,
            value=100_000.0,
            step=10_000.0,
        )
        period = st.date_input(
            "Période de backtest",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )
        start_date, end_date = _coerce_period(period, min_date, max_date)

    if not selected_strategies:
        st.info("Sélectionne au moins une stratégie dans la barre latérale.")
        st.stop()

    with st.spinner("Chargement des données BigQuery filtrées..."):
        daily, daily_error = safe_load(
            load_backtest_daily,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        trades, trades_error = safe_load(
            load_backtest_trades,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        benchmark, benchmark_error = safe_load(
            load_global_benchmark,
            start_date=start_date,
            end_date=end_date,
        )

    blocking_error = daily_error or trades_error
    if blocking_error:
        st.error(blocking_error)
        st.stop()
    if benchmark_error:
        st.warning(
            "L'index benchmark n'a pas pu être chargé. La comparaison stratégie / Buy & Hold reste disponible."
        )

    daily = normalize_date_column(daily)
    trades = normalize_date_column(trades, "trade_date")
    benchmark = normalize_date_column(benchmark)

    if daily.empty:
        st.info("Aucune donnée de backtest disponible pour cette sélection.")
        st.stop()

    selection = BacktestSelection(
        symbol=symbol,
        strategy_names=selected_strategies,
        initial_capital=float(initial_capital),
        start_date=start_date,
        end_date=end_date,
    )
    daily_filtered, trades_filtered, benchmark_filtered = filter_backtest_inputs(
        daily,
        trades,
        benchmark,
        selection,
    )
    buy_hold_selection = BacktestSelection(
        symbol=symbol,
        strategy_names=["buy_and_hold"],
        initial_capital=float(initial_capital),
        start_date=start_date,
        end_date=end_date,
    )
    buy_hold_daily, _, _ = filter_backtest_inputs(
        daily,
        pd.DataFrame(),
        pd.DataFrame(),
        buy_hold_selection,
    )

    if daily_filtered.empty:
        st.info("Aucune donnée ne correspond à cette sélection.")
        st.stop()

    curves = build_portfolio_curves(
        daily=daily_filtered,
        benchmark=benchmark_filtered,
        initial_capital=float(initial_capital),
        buy_hold_daily=buy_hold_daily,
    )
    metrics = compute_curve_metrics(curves, trades_filtered)

    st.subheader(f"{symbol} · {start_date} → {end_date}")
    _display_metric_cards(metrics)

    left_tab, metrics_tab, trades_tab, raw_tab = st.tabs(
        ["Courbes", "Indicateurs", "Transactions", "Données"]
    )

    with left_tab:
        _display_curves(curves)
        _display_drawdown(curves)

    with metrics_tab:
        st.dataframe(
            metrics.sort_values(["series_type", "final_equity"], ascending=[False, False]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "final_equity": st.column_config.NumberColumn("Capital final", format="%.0f €"),
                "pnl": st.column_config.NumberColumn("PnL", format="%.0f €"),
                "cumulative_return": st.column_config.NumberColumn("Performance", format="%.2%"),
                "annualized_volatility": st.column_config.NumberColumn("Vol. annualisée", format="%.2%"),
                "max_drawdown": st.column_config.NumberColumn("Max drawdown", format="%.2%"),
                "outperformance_vs_buy_hold": st.column_config.NumberColumn("Écart vs B&H", format="%.2%"),
                "outperformance_vs_index": st.column_config.NumberColumn("Écart vs index", format="%.2%"),
            },
        )
        st.download_button(
            "Exporter les indicateurs CSV",
            dataframe_to_csv(metrics),
            "backtest_metrics.csv",
            "text/csv",
        )

    with trades_tab:
        if trades_filtered.empty:
            st.info("Aucune transaction sur cette période.")
        else:
            st.dataframe(trades_filtered, use_container_width=True, hide_index=True)
            st.download_button(
                "Exporter les transactions CSV",
                dataframe_to_csv(trades_filtered),
                "backtest_trades.csv",
                "text/csv",
            )

    with raw_tab:
        st.caption("Données mart filtrées utilisées pour recalculer la période sélectionnée.")
        st.dataframe(daily_filtered, use_container_width=True, hide_index=True)
        st.download_button(
            "Exporter les données journalières CSV",
            dataframe_to_csv(daily_filtered),
            "backtest_daily.csv",
            "text/csv",
        )
