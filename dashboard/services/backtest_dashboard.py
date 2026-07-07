from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

TRADING_DAYS_PER_YEAR = 252

EXPECTED_STRATEGY_NAMES = [
    "buy_and_hold",
    "moving_average_cross",
    "moving_average_stoch_rsi",
    "technical_news_filter",
    "breakout_20d",
]


@dataclass(frozen=True)
class BacktestSelection:
    symbol: str
    strategy_names: list[str]
    initial_capital: float
    start_date: date | None = None
    end_date: date | None = None


def normalize_date_column(dataframe: pd.DataFrame, column: str = "date") -> pd.DataFrame:
    if dataframe.empty or column not in dataframe:
        return dataframe.copy()

    normalized = dataframe.copy()
    normalized[column] = pd.to_datetime(normalized[column], errors="coerce").dt.date
    return normalized.dropna(subset=[column])


def filter_backtest_inputs(
    daily: pd.DataFrame,
    trades: pd.DataFrame,
    benchmark: pd.DataFrame,
    selection: BacktestSelection,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily_filtered = normalize_date_column(daily)
    trades_filtered = normalize_date_column(trades, "trade_date")
    benchmark_filtered = normalize_date_column(benchmark)

    if not daily_filtered.empty:
        daily_filtered = daily_filtered[daily_filtered["symbol"] == selection.symbol]
        daily_filtered = daily_filtered[
            daily_filtered["strategy_name"].isin(selection.strategy_names)
        ]
        if selection.start_date:
            daily_filtered = daily_filtered[daily_filtered["date"] >= selection.start_date]
        if selection.end_date:
            daily_filtered = daily_filtered[daily_filtered["date"] <= selection.end_date]

    if not trades_filtered.empty:
        if "symbol" in trades_filtered:
            trades_filtered = trades_filtered[trades_filtered["symbol"] == selection.symbol]
        if "strategy_name" in trades_filtered:
            trades_filtered = trades_filtered[
                trades_filtered["strategy_name"].isin(selection.strategy_names)
            ]
        if selection.start_date and "trade_date" in trades_filtered:
            trades_filtered = trades_filtered[
                trades_filtered["trade_date"] >= selection.start_date
            ]
        if selection.end_date and "trade_date" in trades_filtered:
            trades_filtered = trades_filtered[
                trades_filtered["trade_date"] <= selection.end_date
            ]

    if not benchmark_filtered.empty:
        if selection.start_date:
            benchmark_filtered = benchmark_filtered[
                benchmark_filtered["date"] >= selection.start_date
            ]
        if selection.end_date:
            benchmark_filtered = benchmark_filtered[
                benchmark_filtered["date"] <= selection.end_date
            ]

    return daily_filtered, trades_filtered, benchmark_filtered


def compound_equity(returns: pd.Series, initial_capital: float) -> pd.Series:
    clean_returns = pd.to_numeric(returns, errors="coerce").fillna(0)
    return initial_capital * (1 + clean_returns).cumprod()


def build_portfolio_curves(
    daily: pd.DataFrame,
    benchmark: pd.DataFrame,
    initial_capital: float,
    buy_hold_daily: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame(
            columns=["date", "series_name", "series_type", "equity", "initial_capital"]
        )

    frames: list[pd.DataFrame] = []
    sorted_daily = normalize_date_column(daily).sort_values(["strategy_name", "date"])

    for strategy_name, strategy_rows in sorted_daily.groupby("strategy_name"):
        strategy_frame = strategy_rows[["date"]].copy()
        strategy_frame["series_name"] = str(strategy_name)
        strategy_frame["series_type"] = "strategy"
        strategy_frame["initial_capital"] = initial_capital
        strategy_frame["equity"] = compound_equity(
            strategy_rows.get("net_strategy_return", pd.Series(dtype=float)),
            initial_capital,
        ).to_numpy()
        frames.append(strategy_frame)

    buy_hold_source = buy_hold_daily if buy_hold_daily is not None else pd.DataFrame()
    buy_hold_source = normalize_date_column(buy_hold_source)
    if not buy_hold_source.empty and "net_strategy_return" in buy_hold_source:
        buy_hold_rows = buy_hold_source.sort_values("date")
        buy_hold_return_column = "net_strategy_return"
        buy_hold_label = "Buy & Hold net"
    else:
        buy_hold_rows = sorted_daily.drop_duplicates(subset=["date"]).sort_values("date")
        buy_hold_return_column = "asset_return"
        buy_hold_label = "Buy & Hold actif brut"

    buy_hold = buy_hold_rows[["date"]].copy()
    buy_hold["series_name"] = buy_hold_label
    buy_hold["series_type"] = "buy_hold"
    buy_hold["initial_capital"] = initial_capital
    buy_hold["equity"] = compound_equity(
        buy_hold_rows.get(buy_hold_return_column, pd.Series(dtype=float)),
        initial_capital,
    ).to_numpy()
    frames.append(buy_hold)

    if not benchmark.empty and "daily_return" in benchmark:
        benchmark_rows = normalize_date_column(benchmark).sort_values("date")
        benchmark_rows = benchmark_rows[
            benchmark_rows["date"].isin(buy_hold_rows["date"])
        ]
        if not benchmark_rows.empty:
            benchmark_curve = benchmark_rows[["date"]].copy()
            benchmark_name = (
                benchmark_rows["benchmark_name"].dropna().astype(str).iloc[0]
                if "benchmark_name" in benchmark_rows
                and benchmark_rows["benchmark_name"].notna().any()
                else "Index commodities"
            )
            benchmark_curve["series_name"] = benchmark_name
            benchmark_curve["series_type"] = "benchmark"
            benchmark_curve["initial_capital"] = initial_capital
            benchmark_curve["equity"] = compound_equity(
                benchmark_rows["daily_return"],
                initial_capital,
            ).to_numpy()
            frames.append(benchmark_curve)

    return pd.concat(frames, ignore_index=True).sort_values(
        ["series_type", "series_name", "date"]
    )


def compute_curve_metrics(
    curves: pd.DataFrame,
    trades: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if curves.empty:
        return pd.DataFrame()

    rows = []
    trades = trades if trades is not None else pd.DataFrame()
    for (series_name, series_type), group in curves.sort_values("date").groupby(
        ["series_name", "series_type"]
    ):
        equity = pd.to_numeric(group["equity"], errors="coerce").dropna()
        if equity.empty:
            continue
        initial_capital = (
            float(group["initial_capital"].dropna().iloc[0])
            if "initial_capital" in group and group["initial_capital"].notna().any()
            else float(equity.iloc[0])
        )
        returns = equity.pct_change().fillna(0)
        cumulative_return = (
            equity.iloc[-1] / initial_capital - 1 if initial_capital else 0
        )
        annualized_volatility = returns.std() * (TRADING_DAYS_PER_YEAR**0.5)
        sharpe_ratio = (
            returns.mean() / returns.std() * (TRADING_DAYS_PER_YEAR**0.5)
            if returns.std() and pd.notna(returns.std())
            else 0
        )
        drawdown = equity / equity.cummax() - 1
        trade_count = 0
        if not trades.empty and series_type == "strategy" and "strategy_name" in trades:
            trade_count = int((trades["strategy_name"] == series_name).sum())

        rows.append(
            {
                "series_name": series_name,
                "series_type": series_type,
                "start_date": group["date"].min(),
                "end_date": group["date"].max(),
                "final_equity": equity.iloc[-1],
                "pnl": equity.iloc[-1] - initial_capital,
                "cumulative_return": cumulative_return,
                "annualized_volatility": (
                    annualized_volatility if pd.notna(annualized_volatility) else 0
                ),
                "sharpe_ratio": sharpe_ratio,
                "max_drawdown": drawdown.min() if pd.notna(drawdown.min()) else 0,
                "trade_count": trade_count,
            }
        )

    metrics = pd.DataFrame(rows)
    buy_hold_return = metrics.loc[
        metrics["series_type"] == "buy_hold", "cumulative_return"
    ].max()
    benchmark_return = metrics.loc[
        metrics["series_type"] == "benchmark", "cumulative_return"
    ].max()
    metrics["outperformance_vs_buy_hold"] = (
        metrics["cumulative_return"] - buy_hold_return
        if pd.notna(buy_hold_return)
        else pd.NA
    )
    metrics["outperformance_vs_index"] = (
        metrics["cumulative_return"] - benchmark_return
        if pd.notna(benchmark_return)
        else pd.NA
    )
    return metrics


def format_percentage(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:.2%}"
