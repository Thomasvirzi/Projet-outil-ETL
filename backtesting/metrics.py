from __future__ import annotations

import math

import pandas as pd

from backtesting.models import BacktestResult


def cumulative_return(equity: pd.Series) -> float:
    if equity.empty or equity.iloc[0] == 0:
        return 0.0
    return float(equity.iloc[-1] / equity.iloc[0] - 1)


def annualized_return(equity: pd.Series, periods_per_year: int = 252) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    total_return = equity.iloc[-1] / equity.iloc[0]
    years = len(equity) / periods_per_year
    return float(total_return ** (1 / years) - 1) if years > 0 else 0.0


def annualized_volatility(returns: pd.Series, periods_per_year: int = 252) -> float:
    if len(returns.dropna()) < 2:
        return 0.0
    return float(returns.std(ddof=1) * math.sqrt(periods_per_year))


def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    volatility = annualized_volatility(returns, periods_per_year)
    if volatility == 0:
        return 0.0
    excess_return = returns.mean() * periods_per_year - risk_free_rate
    return float(excess_return / volatility)


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    return float(drawdown.min())


def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    clean_returns = returns.dropna()
    if clean_returns.empty:
        return 0.0

    downside_returns = clean_returns[clean_returns < 0]
    if len(downside_returns) < 2:
        return 0.0

    downside_volatility = downside_returns.std(ddof=1) * math.sqrt(periods_per_year)
    if downside_volatility == 0:
        return 0.0

    excess_return = clean_returns.mean() * periods_per_year - risk_free_rate
    return float(excess_return / downside_volatility)


def calmar_ratio(equity: pd.Series, periods_per_year: int = 252) -> float:
    drawdown = abs(max_drawdown(equity))
    if drawdown == 0:
        return 0.0
    return float(annualized_return(equity, periods_per_year) / drawdown)


def win_rate(trade_returns: pd.Series) -> float:
    clean_returns = trade_returns.dropna()
    if clean_returns.empty:
        return 0.0
    return float((clean_returns > 0).mean())


def profit_factor(trade_returns: pd.Series) -> float:
    clean_returns = trade_returns.dropna()
    gross_profit = clean_returns[clean_returns > 0].sum()
    gross_loss = abs(clean_returns[clean_returns < 0].sum())
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return float(gross_profit / gross_loss)


def average_position_duration(daily_portfolio: pd.DataFrame) -> float:
    if daily_portfolio.empty or "position" not in daily_portfolio:
        return 0.0

    positioned = daily_portfolio.copy()
    positioned["is_in_position"] = positioned["position"].abs() > 0
    durations = []
    current_duration = 0

    for is_in_position in positioned["is_in_position"]:
        if is_in_position:
            current_duration += 1
        elif current_duration > 0:
            durations.append(current_duration)
            current_duration = 0

    if current_duration > 0:
        durations.append(current_duration)

    return float(sum(durations) / len(durations)) if durations else 0.0


def daily_returns_from_equity(equity: pd.Series) -> pd.Series:
    return equity.pct_change().fillna(0)


def summarize_backtest(
    daily_portfolio: pd.DataFrame,
    trades: pd.DataFrame | None = None,
    benchmark_returns: pd.Series | None = None,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.0,
) -> dict[str, float | int]:
    if daily_portfolio.empty:
        return {
            "cumulative_return": 0.0,
            "annualized_return": 0.0,
            "annualized_volatility": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown": 0.0,
            "calmar_ratio": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "trade_count": 0,
            "avg_position_duration": 0.0,
            "total_fees": 0.0,
            "benchmark_cumulative_return": 0.0,
            "benchmark_outperformance": 0.0,
        }

    equity = daily_portfolio["equity"].astype(float)
    strategy_returns = daily_returns_from_equity(equity)
    trades = pd.DataFrame() if trades is None else trades
    total_fees = float(trades["fee"].sum()) if not trades.empty and "fee" in trades else 0.0

    if benchmark_returns is not None and not benchmark_returns.empty:
        benchmark_cumulative_return = float((1 + benchmark_returns.fillna(0)).prod() - 1)
    else:
        benchmark_cumulative_return = 0.0

    cumulative = cumulative_return(equity)

    return {
        "cumulative_return": cumulative,
        "annualized_return": annualized_return(equity, periods_per_year),
        "annualized_volatility": annualized_volatility(strategy_returns, periods_per_year),
        "sharpe_ratio": sharpe_ratio(strategy_returns, risk_free_rate, periods_per_year),
        "sortino_ratio": sortino_ratio(strategy_returns, risk_free_rate, periods_per_year),
        "max_drawdown": max_drawdown(equity),
        "calmar_ratio": calmar_ratio(equity, periods_per_year),
        "win_rate": win_rate(strategy_returns),
        "profit_factor": profit_factor(strategy_returns),
        "trade_count": int(len(trades)),
        "avg_position_duration": average_position_duration(daily_portfolio),
        "total_fees": total_fees,
        "benchmark_cumulative_return": benchmark_cumulative_return,
        "benchmark_outperformance": cumulative - benchmark_cumulative_return,
    }


def summarize_result(
    result: BacktestResult,
    benchmark_returns: pd.Series | None = None,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.0,
) -> dict[str, float | int | str]:
    daily_portfolio = pd.DataFrame([row.__dict__ for row in result.daily_portfolio])
    trades = pd.DataFrame([trade.__dict__ for trade in result.trades])
    summary = summarize_backtest(
        daily_portfolio=daily_portfolio,
        trades=trades,
        benchmark_returns=benchmark_returns,
        periods_per_year=periods_per_year,
        risk_free_rate=risk_free_rate,
    )
    return {
        "strategy_name": result.strategy_name,
        "symbol": daily_portfolio["symbol"].iloc[0] if not daily_portfolio.empty else "",
        **summary,
    }


def compare_backtest_results(
    results: list[BacktestResult],
    benchmark_returns_by_symbol: dict[str, pd.Series] | None = None,
) -> pd.DataFrame:
    benchmark_returns_by_symbol = benchmark_returns_by_symbol or {}
    rows = []

    for result in results:
        daily_portfolio = pd.DataFrame([row.__dict__ for row in result.daily_portfolio])
        symbol = daily_portfolio["symbol"].iloc[0] if not daily_portfolio.empty else ""
        rows.append(
            summarize_result(
                result,
                benchmark_returns=benchmark_returns_by_symbol.get(symbol),
            )
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(
        ["benchmark_outperformance", "sharpe_ratio", "cumulative_return"],
        ascending=[False, False, False],
    )


def compute_trade_returns(trades: pd.DataFrame) -> pd.Series:
    """Realized return per sell, using a weighted-average-cost basis for the position.

    Complements profit_factor/win_rate (computed on daily strategy returns) with a
    trade-level view, for round-trip P&L reporting (e.g. "average return per trade").
    """
    if trades.empty or not {"date", "action", "quantity", "price", "fee"}.issubset(trades.columns):
        return pd.Series(dtype=float)

    ordered = trades.sort_values("date")
    position = 0.0
    cost_basis = 0.0
    realized_returns: list[float] = []

    for row in ordered.itertuples(index=False):
        quantity = abs(float(row.quantity))
        price = float(row.price)
        fee = float(row.fee)

        if row.action == "buy":
            cost_basis += quantity * price + fee
            position += quantity
        elif row.action == "sell" and position > 1e-12:
            sold_quantity = min(quantity, position)
            sold_fraction = sold_quantity / position
            allocated_cost = cost_basis * sold_fraction
            proceeds = sold_quantity * price - fee
            if allocated_cost > 0:
                realized_returns.append(proceeds / allocated_cost - 1)
            cost_basis -= allocated_cost
            position -= sold_quantity

    return pd.Series(realized_returns, dtype=float)


def average_trade_return(trades: pd.DataFrame) -> float:
    returns = compute_trade_returns(trades)
    return float(returns.mean()) if not returns.empty else 0.0


def trade_win_rate(trades: pd.DataFrame) -> float:
    returns = compute_trade_returns(trades)
    return win_rate(returns)


def cumulative_fees(trades: pd.DataFrame) -> float:
    if trades.empty or "fee" not in trades:
        return 0.0
    return float(trades["fee"].sum())


def cumulative_slippage(trades: pd.DataFrame) -> float:
    if trades.empty or "slippage" not in trades:
        return 0.0
    return float(trades["slippage"].sum())


def average_exposure(daily_portfolio: pd.DataFrame) -> float:
    if daily_portfolio.empty or "exposure" not in daily_portfolio:
        return 0.0
    return float(daily_portfolio["exposure"].mean())


def turnover_ratio(trades: pd.DataFrame, daily_portfolio: pd.DataFrame) -> float:
    """Ratio of total traded notional to average portfolio equity (not annualized)."""
    if trades.empty or "gross_amount" not in trades:
        return 0.0
    if daily_portfolio.empty or "equity" not in daily_portfolio:
        return 0.0

    average_equity = daily_portfolio["equity"].mean()
    if average_equity == 0:
        return 0.0
    return float(trades["gross_amount"].sum() / average_equity)


def extended_trade_metrics(trades: pd.DataFrame, daily_portfolio: pd.DataFrame) -> dict[str, float]:
    """Additional per-trade/exposure metrics not covered by summarize_backtest."""
    return {
        "average_trade_return": average_trade_return(trades),
        "trade_win_rate": trade_win_rate(trades),
        "total_fees": cumulative_fees(trades),
        "total_slippage": cumulative_slippage(trades),
        "average_exposure": average_exposure(daily_portfolio),
        "turnover_ratio": turnover_ratio(trades, daily_portfolio),
    }
