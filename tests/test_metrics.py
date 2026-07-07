import math
from datetime import UTC, datetime

import pandas as pd

from backtesting.engine import BacktestEngine
from backtesting.metrics import (
    annualized_return,
    annualized_volatility,
    average_position_duration,
    calmar_ratio,
    compare_backtest_results,
    cumulative_return,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    summarize_backtest,
    win_rate,
)
from backtesting.models import BacktestConfig
from backtesting.strategies import BuyAndHoldStrategy, MovingAverageCrossStrategy


def sample_daily_portfolio() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=5),
            "symbol": ["GC=F"] * 5,
            "equity": [100_000, 101_000, 99_000, 103_000, 102_000],
            "position": [0, 1, 1, 0, 1],
        }
    )


def sample_trades() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fee": [10.0, 12.0, 9.0],
            "slippage": [5.0, 6.0, 4.5],
        }
    )


def sample_market_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=5),
            "symbol": ["GC=F"] * 5,
            "close": [100.0, 101.0, 102.0, 103.0, 104.0],
            "sma_20": [100.0, 101.0, 102.0, 103.0, 104.0],
            "sma_50": [99.0, 100.0, 101.0, 102.0, 103.0],
        }
    )


def test_core_performance_metrics_are_computed() -> None:
    equity = sample_daily_portfolio()["equity"]
    returns = equity.pct_change().fillna(0)

    assert math.isclose(cumulative_return(equity), 0.02)
    assert annualized_return(equity) > 0
    assert annualized_volatility(returns) > 0
    assert sharpe_ratio(returns) != 0
    assert sortino_ratio(returns) != 0
    assert max_drawdown(equity) < 0
    assert calmar_ratio(equity) > 0


def test_trade_quality_metrics_are_computed() -> None:
    trade_returns = pd.Series([0.10, -0.05, 0.03])

    assert win_rate(trade_returns) == 2 / 3
    assert math.isclose(profit_factor(trade_returns), 2.6)
    assert average_position_duration(sample_daily_portfolio()) == 1.5


def test_summarize_backtest_includes_step_12_outputs() -> None:
    summary = summarize_backtest(
        daily_portfolio=sample_daily_portfolio(),
        trades=sample_trades(),
        benchmark_returns=pd.Series([0.0, 0.01, 0.0, -0.01, 0.02]),
    )

    expected_keys = {
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
        "avg_position_duration",
        "total_fees",
        "benchmark_cumulative_return",
        "benchmark_outperformance",
    }

    assert expected_keys.issubset(summary)
    assert summary["trade_count"] == 3
    assert summary["total_fees"] == 31.0


def test_compare_backtest_results_ranks_strategies() -> None:
    config = BacktestConfig(
        strategy_name="comparison",
        initial_capital=1_000,
        fee_rate=0,
        slippage_rate=0,
        run_at=datetime(2026, 1, 6, tzinfo=UTC),
    )
    engine = BacktestEngine(config)
    results = engine.run_many(
        sample_market_data(),
        [BuyAndHoldStrategy(), MovingAverageCrossStrategy()],
    )

    comparison = compare_backtest_results(results)

    assert set(comparison["strategy_name"]) == {"buy_and_hold", "moving_average_cross"}
    assert "benchmark_outperformance" in comparison.columns
