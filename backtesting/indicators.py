from __future__ import annotations

import numpy as np
import pandas as pd

SMA_WINDOWS = (20, 50, 100, 200)
RSI_WINDOW = 14
STOCH_RSI_WINDOW = 14
STOCH_RSI_SMOOTHING = 3
ATR_WINDOW = 14
BOLLINGER_WINDOW = 20
VOLATILITY_WINDOW = 20
VOLUME_WINDOW = 20
EMA_SHORT_SPAN = 12
EMA_LONG_SPAN = 26
MACD_SIGNAL_SPAN = 9
TRADING_DAYS_PER_YEAR = 252

REQUIRED_COLUMNS = {"date", "symbol", "close"}


def compute_technical_indicators(data: pd.DataFrame, price_column: str = "close") -> pd.DataFrame:
    """Compute technical indicators per symbol, using only past and current rows.

    Mirrors the formulas used in dbt_finance/models/warehouse/int_technical_indicators.sql
    (simple-average RSI, not Wilder smoothing) so strategies written against the SQL-derived
    columns behave the same way against this Python-computed frame. All rolling windows are
    right-aligned (current row + preceding rows only), so no future information leaks into a
    given day's indicators.
    """
    missing_columns = REQUIRED_COLUMNS - set(data.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Missing required columns: {missing}")
    if price_column not in data.columns:
        raise ValueError(f"Missing price column: {price_column}")

    working = data.sort_values(["symbol", "date"]).reset_index(drop=True).copy()
    working[price_column] = pd.to_numeric(working[price_column], errors="coerce")

    grouped_price = working.groupby("symbol")[price_column]
    previous_price = grouped_price.shift(1)

    working["simple_return"] = (working[price_column] - previous_price) / previous_price
    working["log_return"] = np.log(working[price_column] / previous_price)
    working["log_return"] = working["log_return"].where(
        (working[price_column] > 0) & (previous_price > 0)
    )

    for window in SMA_WINDOWS:
        working[f"sma_{window}"] = grouped_price.transform(
            lambda values, window=window: values.rolling(window, min_periods=window).mean()
        )

    close_stddev_20d = grouped_price.transform(
        lambda values: values.rolling(BOLLINGER_WINDOW, min_periods=BOLLINGER_WINDOW).std(ddof=1)
    )
    working["bollinger_upper_20d"] = working["sma_20"] + 2 * close_stddev_20d
    working["bollinger_lower_20d"] = working["sma_20"] - 2 * close_stddev_20d

    working["volatility_20d"] = working.groupby("symbol")["simple_return"].transform(
        lambda values: values.rolling(VOLATILITY_WINDOW, min_periods=VOLATILITY_WINDOW).std(ddof=1)
    )
    working["historical_volatility_20d"] = working["volatility_20d"] * np.sqrt(TRADING_DAYS_PER_YEAR)

    if "volume" in working.columns:
        working["volume"] = pd.to_numeric(working["volume"], errors="coerce")
        volume_avg_20d = working.groupby("symbol")["volume"].transform(
            lambda values: values.rolling(VOLUME_WINDOW, min_periods=VOLUME_WINDOW).mean()
        )
        working["volume_ratio_20d"] = working["volume"] / volume_avg_20d

    if {"high", "low"}.issubset(working.columns):
        high = pd.to_numeric(working["high"], errors="coerce")
        low = pd.to_numeric(working["low"], errors="coerce")
        previous_close = previous_price.fillna(working[price_column])
        true_range = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        working["true_range"] = true_range
        working["atr_14"] = working.groupby("symbol")["true_range"].transform(
            lambda values: values.rolling(ATR_WINDOW, min_periods=ATR_WINDOW).mean()
        )
        working = working.drop(columns="true_range")

    working = _add_rsi(working, price_column, previous_price)
    working = _add_stochastic_rsi(working)
    working = _add_macd(working, price_column)

    return working


def _add_rsi(data: pd.DataFrame, price_column: str, previous_price: pd.Series) -> pd.DataFrame:
    delta = data[price_column] - previous_price
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    data = data.copy()
    data["_gain"] = gain
    data["_loss"] = loss

    avg_gain = data.groupby("symbol")["_gain"].transform(
        lambda values: values.rolling(RSI_WINDOW, min_periods=RSI_WINDOW).mean()
    )
    avg_loss = data.groupby("symbol")["_loss"].transform(
        lambda values: values.rolling(RSI_WINDOW, min_periods=RSI_WINDOW).mean()
    )

    rsi = 100 - (100 / (1 + avg_gain / avg_loss))
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain > 0)), 100.0)
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)
    data["rsi_14"] = rsi

    return data.drop(columns=["_gain", "_loss"])


def _add_stochastic_rsi(data: pd.DataFrame) -> pd.DataFrame:
    rsi_min = data.groupby("symbol")["rsi_14"].transform(
        lambda values: values.rolling(STOCH_RSI_WINDOW, min_periods=STOCH_RSI_WINDOW).min()
    )
    rsi_max = data.groupby("symbol")["rsi_14"].transform(
        lambda values: values.rolling(STOCH_RSI_WINDOW, min_periods=STOCH_RSI_WINDOW).max()
    )

    stochastic_rsi_k = 100 * (data["rsi_14"] - rsi_min) / (rsi_max - rsi_min)
    stochastic_rsi_k = stochastic_rsi_k.where(rsi_max != rsi_min, 50.0)
    data = data.copy()
    data["stochastic_rsi_k"] = stochastic_rsi_k
    data["stochastic_rsi_d"] = data.groupby("symbol")["stochastic_rsi_k"].transform(
        lambda values: values.rolling(STOCH_RSI_SMOOTHING, min_periods=STOCH_RSI_SMOOTHING).mean()
    )
    return data


def _add_macd(data: pd.DataFrame, price_column: str) -> pd.DataFrame:
    data = data.copy()
    grouped_price = data.groupby("symbol")[price_column]

    data["ema_12"] = grouped_price.transform(
        lambda values: values.ewm(span=EMA_SHORT_SPAN, adjust=False, min_periods=EMA_SHORT_SPAN).mean()
    )
    data["ema_26"] = grouped_price.transform(
        lambda values: values.ewm(span=EMA_LONG_SPAN, adjust=False, min_periods=EMA_LONG_SPAN).mean()
    )
    data["macd"] = data["ema_12"] - data["ema_26"]
    data["macd_signal"] = data.groupby("symbol")["macd"].transform(
        lambda values: values.ewm(span=MACD_SIGNAL_SPAN, adjust=False, min_periods=MACD_SIGNAL_SPAN).mean()
    )
    data["macd_histogram"] = data["macd"] - data["macd_signal"]
    return data
