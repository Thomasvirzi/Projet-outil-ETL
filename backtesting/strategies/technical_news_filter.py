from __future__ import annotations

import pandas as pd

from backtesting.strategies.base import Strategy


def _numeric_series_or_default(
    data: pd.DataFrame,
    column: str,
    default: float = 0.0,
) -> pd.Series:
    if column not in data:
        return pd.Series(default, index=data.index)
    return pd.to_numeric(data[column], errors="coerce").fillna(default)


class TechnicalNewsFilterStrategy(Strategy):
    name = "technical_news_filter"

    def __init__(
        self,
        min_sentiment_score: float = -0.15,
        max_geopolitical_risk: float = 0.75,
        max_supply_shock_risk: float = 0.75,
    ) -> None:
        self.min_sentiment_score = min_sentiment_score
        self.max_geopolitical_risk = max_geopolitical_risk
        self.max_supply_shock_risk = max_supply_shock_risk

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        weighted_sentiment_score = _numeric_series_or_default(
            data,
            "weighted_sentiment_score",
        )
        geopolitical_risk_score = _numeric_series_or_default(
            data,
            "geopolitical_risk_score",
        )
        supply_shock_score = _numeric_series_or_default(
            data,
            "supply_shock_score",
        )

        technical_condition = (
            (data["close"] > data["sma_20"])
            & (data["sma_20"] >= data["sma_50"])
            & data["rsi_14"].between(30, 75)
        )
        news_condition = (
            (weighted_sentiment_score >= self.min_sentiment_score)
            & (geopolitical_risk_score < self.max_geopolitical_risk)
            & (supply_shock_score < self.max_supply_shock_risk)
        )

        signals = (technical_condition & news_condition).fillna(False).astype(int)
        reasons = pd.Series("flat_technical_or_news_filter", index=data.index)
        reasons.loc[signals == 1] = "technical_trend_confirmed_by_news"
        return self._result(data, signals, reasons)
