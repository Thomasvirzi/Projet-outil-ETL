from __future__ import annotations

from datetime import date

import pandas as pd


def filter_dataframe(
    dataframe: pd.DataFrame,
    *,
    symbol: str | None = None,
    category: str | None = None,
    strategy_name: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    date_column: str = "date",
) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe

    filtered = dataframe.copy()

    if symbol and "symbol" in filtered:
        filtered = filtered[filtered["symbol"] == symbol]
    if category and "category" in filtered:
        filtered = filtered[filtered["category"] == category]
    if strategy_name and "strategy_name" in filtered:
        filtered = filtered[filtered["strategy_name"] == strategy_name]
    if date_column in filtered and (start_date or end_date):
        dates = pd.to_datetime(filtered[date_column]).dt.date
        if start_date:
            filtered = filtered[dates >= start_date]
            dates = pd.to_datetime(filtered[date_column]).dt.date
        if end_date:
            filtered = filtered[dates <= end_date]

    return filtered


def dataframe_to_csv(dataframe: pd.DataFrame) -> bytes:
    return dataframe.to_csv(index=False).encode("utf-8")


def unique_values(dataframe: pd.DataFrame, column: str) -> list[str]:
    if dataframe.empty or column not in dataframe:
        return []
    return sorted(value for value in dataframe[column].dropna().astype(str).unique().tolist() if value)

