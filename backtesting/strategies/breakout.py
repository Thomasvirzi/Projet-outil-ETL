from __future__ import annotations

import pandas as pd

from backtesting.strategies.base import Strategy


class BreakoutStrategy(Strategy):
    name = "breakout_20d"

    def __init__(self, lookback: int = 20, exit_lookback: int = 10) -> None:
        self.lookback = lookback
        self.exit_lookback = exit_lookback

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        working = data.sort_values(["symbol", "date"]).copy()
        previous_high = working.groupby("symbol")["close"].transform(
            lambda values: values.rolling(self.lookback, min_periods=1).max().shift(1)
        )
        previous_low = working.groupby("symbol")["close"].transform(
            lambda values: values.rolling(self.exit_lookback, min_periods=1).min().shift(1)
        )

        signals = pd.Series(0, index=working.index)
        reasons = pd.Series("flat_no_breakout", index=working.index)
        for _, symbol_rows in working.groupby("symbol", sort=False):
            in_position = False
            for index, row in symbol_rows.iterrows():
                enters = pd.notna(previous_high.loc[index]) and row["close"] > previous_high.loc[index]
                exits = pd.notna(previous_low.loc[index]) and row["close"] < previous_low.loc[index]
                if in_position and exits:
                    in_position = False
                    reasons.loc[index] = "exit_breaks_previous_low"
                elif enters:
                    in_position = True
                    reasons.loc[index] = "entry_breaks_previous_high"
                elif in_position:
                    reasons.loc[index] = "hold_after_breakout"

                signals.loc[index] = int(in_position)

        return self._result(data, signals.reindex(data.index), reasons.reindex(data.index))
