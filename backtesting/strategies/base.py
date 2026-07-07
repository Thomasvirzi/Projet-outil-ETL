from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    name: str

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """Return a dataframe with date, symbol, signal and reason columns."""

    def _result(self, data: pd.DataFrame, signals: pd.Series, reasons: pd.Series) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": data["date"],
                "symbol": data["symbol"],
                "signal": signals.astype(int),
                "reason": reasons,
            }
        )

