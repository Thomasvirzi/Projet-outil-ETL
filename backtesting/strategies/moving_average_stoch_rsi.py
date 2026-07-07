from __future__ import annotations

import pandas as pd

from backtesting.strategies.base import Strategy


class MovingAverageStochRsiStrategy(Strategy):
    name = "moving_average_stoch_rsi"

    def __init__(self, oversold_threshold: float = 20.0, exit_threshold: float = 80.0) -> None:
        self.oversold_threshold = oversold_threshold
        self.exit_threshold = exit_threshold

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        trend_is_positive = data["sma_20"] >= data["sma_50"]
        momentum_entry = data["stochastic_rsi_k"] >= self.oversold_threshold
        momentum_not_overheated = data["stochastic_rsi_d"] <= self.exit_threshold
        long_condition = trend_is_positive & momentum_entry & momentum_not_overheated

        signals = long_condition.fillna(False).astype(int)
        reasons = pd.Series("flat_stoch_rsi_filter", index=data.index)
        reasons.loc[signals == 1] = "trend_confirmed_by_stoch_rsi"
        return self._result(data, signals, reasons)

