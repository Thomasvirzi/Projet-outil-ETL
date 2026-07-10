import numpy as np
import pandas as pd
import pytest

from backtesting.indicators import compute_technical_indicators


def _price_series(n: int = 40, symbol: str = "TEST") -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    rng = np.random.default_rng(42)
    prices = 150.0 + np.cumsum(rng.normal(0, 1.5, n))
    prices = np.abs(prices) + 50.0
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "close": prices,
            "high": prices * 1.01,
            "low": prices * 0.99,
            "volume": 1_000_000.0,
        }
    )


def test_sma_matches_manual_rolling_mean() -> None:
    data = _price_series(30)

    result = compute_technical_indicators(data)

    expected = data["close"].rolling(20, min_periods=20).mean()
    pd.testing.assert_series_equal(
        result["sma_20"].reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )


def test_rsi_is_bounded_between_0_and_100() -> None:
    data = _price_series(60)

    result = compute_technical_indicators(data)
    rsi = result["rsi_14"].dropna()

    assert not rsi.empty
    assert rsi.between(0, 100).all()


def test_stochastic_rsi_is_bounded_between_0_and_100() -> None:
    data = _price_series(60)

    result = compute_technical_indicators(data)
    stochastic = result[["stochastic_rsi_k", "stochastic_rsi_d"]].dropna()

    assert not stochastic.empty
    assert (stochastic >= 0).all().all()
    assert (stochastic <= 100).all().all()


def test_indicators_do_not_look_ahead() -> None:
    full = _price_series(50)
    truncated = full.iloc[:30].copy()

    full_result = compute_technical_indicators(full)
    truncated_result = compute_technical_indicators(truncated)

    columns = ["sma_20", "sma_50", "rsi_14", "stochastic_rsi_k", "macd", "atr_14"]
    common_rows = min(len(full_result), len(truncated_result))

    pd.testing.assert_frame_equal(
        full_result.loc[: common_rows - 1, columns].reset_index(drop=True),
        truncated_result.loc[: common_rows - 1, columns].reset_index(drop=True),
    )


def test_indicators_are_independent_per_symbol() -> None:
    first = _price_series(30, symbol="AAA")
    second = _price_series(30, symbol="BBB")
    second["close"] = second["close"] * 3
    second["high"] = second["close"] * 1.01
    second["low"] = second["close"] * 0.99

    combined = compute_technical_indicators(pd.concat([first, second], ignore_index=True))
    solo = compute_technical_indicators(first)

    merged_first = combined.loc[combined["symbol"] == "AAA", "sma_20"].reset_index(drop=True)
    pd.testing.assert_series_equal(merged_first, solo["sma_20"], check_names=False)


def test_missing_required_columns_raise() -> None:
    with pytest.raises(ValueError, match="Missing required columns"):
        compute_technical_indicators(pd.DataFrame({"date": [1], "symbol": ["A"]}))
