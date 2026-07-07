import pandas as pd

from backtesting.strategies import (
    BreakoutStrategy,
    MovingAverageCrossStrategy,
    MovingAverageStochRsiStrategy,
    TechnicalNewsFilterStrategy,
)


def sample_signal_data() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2026-01-01",
                "symbol": "GC=F",
                "close": 100.0,
                "sma_20": 101.0,
                "sma_50": 102.0,
                "stochastic_rsi_k": 10.0,
                "stochastic_rsi_d": 85.0,
                "rsi_14": 80.0,
                "weighted_sentiment_score": -0.5,
                "geopolitical_risk_score": 0.9,
                "supply_shock_score": 0.9,
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
                "weighted_sentiment_score": 0.1,
                "geopolitical_risk_score": 0.2,
                "supply_shock_score": 0.2,
            },
            {
                "date": "2026-01-03",
                "symbol": "GC=F",
                "close": 108.0,
                "sma_20": 106.0,
                "sma_50": 101.0,
                "stochastic_rsi_k": 40.0,
                "stochastic_rsi_d": 50.0,
                "rsi_14": 62.0,
                "weighted_sentiment_score": 0.2,
                "geopolitical_risk_score": 0.2,
                "supply_shock_score": 0.2,
            },
        ]
    )


def test_moving_average_cross_rule_switches_long_when_short_average_above_long() -> None:
    signals = MovingAverageCrossStrategy().generate_signals(sample_signal_data())

    assert signals["signal"].tolist() == [0, 1, 1]
    assert signals["reason"].iloc[1] == "short_average_above_long_average"


def test_moving_average_stoch_rsi_requires_trend_and_momentum_filter() -> None:
    signals = MovingAverageStochRsiStrategy().generate_signals(sample_signal_data())

    assert signals["signal"].tolist() == [0, 1, 1]
    assert signals["reason"].iloc[0] == "flat_stoch_rsi_filter"


def test_technical_news_filter_blocks_bad_news_risk() -> None:
    data = sample_signal_data()
    data.loc[1, "geopolitical_risk_score"] = 0.95

    signals = TechnicalNewsFilterStrategy().generate_signals(data)

    assert signals["signal"].tolist() == [0, 0, 1]
    assert signals["reason"].iloc[1] == "flat_technical_or_news_filter"


def test_technical_news_filter_applies_each_nlp_threshold() -> None:
    base_data = sample_signal_data().iloc[[1]].copy()
    strategy = TechnicalNewsFilterStrategy()

    assert strategy.generate_signals(base_data)["signal"].tolist() == [1]

    low_sentiment = base_data.copy()
    low_sentiment["weighted_sentiment_score"] = -0.16
    assert strategy.generate_signals(low_sentiment)["signal"].tolist() == [0]

    high_geopolitical_risk = base_data.copy()
    high_geopolitical_risk["geopolitical_risk_score"] = 0.75
    assert strategy.generate_signals(high_geopolitical_risk)["signal"].tolist() == [0]

    high_supply_shock = base_data.copy()
    high_supply_shock["supply_shock_score"] = 0.75
    assert strategy.generate_signals(high_supply_shock)["signal"].tolist() == [0]


def test_technical_news_filter_defaults_missing_nlp_columns_to_neutral() -> None:
    data = sample_signal_data().iloc[[1]].drop(
        columns=[
            "weighted_sentiment_score",
            "geopolitical_risk_score",
            "supply_shock_score",
        ]
    )

    signals = TechnicalNewsFilterStrategy().generate_signals(data)

    assert signals["signal"].tolist() == [1]


def test_breakout_uses_previous_high_without_lookahead() -> None:
    signals = BreakoutStrategy(lookback=2).generate_signals(sample_signal_data())

    assert signals["signal"].tolist() == [0, 1, 1]
    assert signals["reason"].tolist() == [
        "flat_no_breakout",
        "entry_breaks_previous_high",
        "hold_after_breakout",
    ]


def test_breakout_exits_when_close_breaks_previous_low() -> None:
    data = pd.DataFrame(
        [
            {"date": "2026-01-01", "symbol": "SB=F", "close": 100.0},
            {"date": "2026-01-02", "symbol": "SB=F", "close": 105.0},
            {"date": "2026-01-03", "symbol": "SB=F", "close": 104.0},
            {"date": "2026-01-04", "symbol": "SB=F", "close": 99.0},
        ]
    )

    signals = BreakoutStrategy(lookback=1, exit_lookback=2).generate_signals(data)

    assert signals["signal"].tolist() == [0, 1, 1, 0]
    assert signals["reason"].iloc[-1] == "exit_breaks_previous_low"
