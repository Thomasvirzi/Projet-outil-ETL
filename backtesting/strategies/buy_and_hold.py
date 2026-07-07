from __future__ import annotations

import pandas as pd

from backtesting.strategies.base import Strategy


class BuyAndHoldStrategy(Strategy):
    name = "buy_and_hold"

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        signals = pd.Series(1, index=data.index)
        reasons = pd.Series("hold_long_baseline", index=data.index)
        return self._result(data, signals, reasons)

