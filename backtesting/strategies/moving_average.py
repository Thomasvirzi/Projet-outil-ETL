from __future__ import annotations

import pandas as pd

from backtesting.strategies.base import Strategy


class MovingAverageCrossStrategy(Strategy):
    name = "moving_average_cross"

    def __init__(self, short_window_column: str = "sma_20", long_window_column: str = "sma_50") -> None:
        self.short_window_column = short_window_column
        self.long_window_column = long_window_column

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        long_condition = data[self.short_window_column] >= data[self.long_window_column]
        signals = long_condition.fillna(False).astype(int)
        reasons = pd.Series("flat_below_long_average", index=data.index)
        reasons.loc[signals == 1] = "short_average_above_long_average"
        return self._result(data, signals, reasons)

