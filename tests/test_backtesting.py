from datetime import UTC, datetime

import pandas as pd

from backtesting.engine import BacktestEngine
from backtesting.models import BacktestConfig
from backtesting.strategies import (
    BreakoutStrategy,
    BuyAndHoldStrategy,
    MovingAverageCrossStrategy,
    MovingAverageStochRsiStrategy,
    TechnicalNewsFilterStrategy,
)


def sample_market_data() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2026-01-01",
                "symbol": "GC=F",
                "close": 100.0,
                "sma_20": 100.0,
                "sma_50": 99.0,
                "stochastic_rsi_k": 30.0,
                "stochastic_rsi_d": 40.0,
                "rsi_14": 55.0,
                "weighted_sentiment_score": 0.1,
                "geopolitical_risk_score": 0.2,
                "supply_shock_score": 0.2,
            },
            {
                "date": "2026-01-02",
                "symbol": "GC=F",
                "close": 110.0,
                "sma_20": 105.0,
                "sma_50": 100.0,
                "stochastic_rsi_k": 35.0,
                "stochastic_rsi_d": 45.0,
                "rsi_14": 60.0,
                "weighted_sentiment_score": 0.2,
                "geopolitical_risk_score": 0.2,
                "supply_shock_score": 0.2,
            },
            {
                "date": "2026-01-03",
                "symbol": "GC=F",
                "close": 120.0,
                "sma_20": 106.0,
                "sma_50": 101.0,
                "stochastic_rsi_k": 45.0,
                "stochastic_rsi_d": 50.0,
                "rsi_14": 62.0,
                "weighted_sentiment_score": 0.2,
                "geopolitical_risk_score": 0.2,
                "supply_shock_score": 0.2,
            },
        ]
    )


def test_buy_and_hold_executes_first_signal_on_next_day() -> None:
    config = BacktestConfig(
        strategy_name="buy_and_hold",
        initial_capital=1_000,
        fee_rate=0,
        slippage_rate=0,
        run_at=datetime(2026, 1, 4, tzinfo=UTC),
    )
    result = BacktestEngine(config).run(sample_market_data(), BuyAndHoldStrategy())

    assert result.daily_portfolio[0].executed_signal == 0
    assert result.daily_portfolio[0].position == 0
    assert result.daily_portfolio[1].executed_signal == 1
    assert result.trades[0].date == pd.to_datetime("2026-01-02").date()


def test_engine_blocks_short_positions_for_mvp() -> None:
    data = sample_market_data()
    data["sma_20"] = 90
    data["sma_50"] = 100
    config = BacktestConfig(
        strategy_name="moving_average_cross",
        initial_capital=1_000,
        allow_short=False,
    )
    result = BacktestEngine(config).run(data, MovingAverageCrossStrategy())

    assert result.trades == []
    assert all(row.position == 0 for row in result.daily_portfolio)


def test_costs_and_slippage_reduce_cash_on_entry() -> None:
    config = BacktestConfig(
        strategy_name="buy_and_hold",
        initial_capital=1_000,
        fee_rate=0.01,
        slippage_rate=0.01,
    )
    result = BacktestEngine(config).run(sample_market_data(), BuyAndHoldStrategy())

    assert result.trades[0].fee > 0
    assert result.trades[0].slippage > 0
    assert result.trades[0].cash_after < 1_000


def test_mvp_strategies_generate_expected_signal_columns() -> None:
    data = sample_market_data()
    strategies = [
        BuyAndHoldStrategy(),
        MovingAverageCrossStrategy(),
        MovingAverageStochRsiStrategy(),
        TechnicalNewsFilterStrategy(),
        BreakoutStrategy(),
    ]

    for strategy in strategies:
        signals = strategy.generate_signals(data)
        assert {"date", "symbol", "signal", "reason"}.issubset(signals.columns)
        assert signals["signal"].isin([-1, 0, 1]).all()
