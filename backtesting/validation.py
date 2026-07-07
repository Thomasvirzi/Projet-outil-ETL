from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class ValidationPeriod:
    name: str
    start_date: date
    end_date: date | None
    purpose: str
    is_optimization_allowed: bool


DEFAULT_VALIDATION_PERIODS = [
    ValidationPeriod(
        name="calibration",
        start_date=date(2020, 1, 1),
        end_date=date(2023, 12, 31),
        purpose="Conception des règles et calibration des paramètres.",
        is_optimization_allowed=True,
    ),
    ValidationPeriod(
        name="validation",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        purpose="Choix final des paramètres sans toucher au test final.",
        is_optimization_allowed=True,
    ),
    ValidationPeriod(
        name="test",
        start_date=date(2025, 1, 1),
        end_date=None,
        purpose="Évaluation hors échantillon finale.",
        is_optimization_allowed=False,
    ),
]


def assign_validation_periods(
    data: pd.DataFrame,
    *,
    date_column: str = "date",
    periods: Iterable[ValidationPeriod] = DEFAULT_VALIDATION_PERIODS,
) -> pd.DataFrame:
    if date_column not in data.columns:
        raise ValueError(f"Missing date column: {date_column}")

    result = data.copy()
    result[date_column] = pd.to_datetime(result[date_column]).dt.date
    result["validation_period"] = "out_of_scope"
    result["validation_purpose"] = "Hors périmètre de validation."
    result["is_optimization_allowed"] = False

    for period in periods:
        mask = result[date_column] >= period.start_date
        if period.end_date is not None:
            mask &= result[date_column] <= period.end_date

        result.loc[mask, "validation_period"] = period.name
        result.loc[mask, "validation_purpose"] = period.purpose
        result.loc[mask, "is_optimization_allowed"] = period.is_optimization_allowed

    return result


def assert_no_test_period_optimization(selected_periods: Iterable[str]) -> None:
    normalized_periods = {period.lower() for period in selected_periods}
    if "test" in normalized_periods:
        raise ValueError("The final test period cannot be used for parameter optimization.")


def summarize_by_period(metrics: pd.DataFrame) -> pd.DataFrame:
    required_columns = {"validation_period", "strategy_name", "symbol", "cumulative_return", "sharpe_ratio", "max_drawdown"}
    missing_columns = required_columns - set(metrics.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Missing required columns: {missing}")

    return (
        metrics.groupby(["validation_period", "strategy_name"], as_index=False)
        .agg(
            symbols_tested=("symbol", "nunique"),
            avg_cumulative_return=("cumulative_return", "mean"),
            median_cumulative_return=("cumulative_return", "median"),
            avg_sharpe_ratio=("sharpe_ratio", "mean"),
            worst_max_drawdown=("max_drawdown", "min"),
            positive_symbols=("cumulative_return", lambda values: int((values > 0).sum())),
        )
        .assign(
            positive_symbol_rate=lambda frame: frame["positive_symbols"] / frame["symbols_tested"].replace(0, pd.NA)
        )
    )


def measure_rss_filter_contribution(
    metrics: pd.DataFrame,
    *,
    technical_strategy: str = "moving_average_cross",
    rss_strategy: str = "technical_news_filter",
) -> pd.DataFrame:
    required_columns = {
        "validation_period",
        "symbol",
        "strategy_name",
        "cumulative_return",
        "sharpe_ratio",
        "max_drawdown",
    }
    missing_columns = required_columns - set(metrics.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Missing required columns: {missing}")

    technical = metrics[metrics["strategy_name"] == technical_strategy].copy()
    rss = metrics[metrics["strategy_name"] == rss_strategy].copy()

    comparison = rss.merge(
        technical,
        on=["validation_period", "symbol"],
        suffixes=("_rss", "_technical"),
    )

    if comparison.empty:
        return pd.DataFrame(
            columns=[
                "validation_period",
                "symbol",
                "return_delta",
                "sharpe_delta",
                "drawdown_delta",
                "rss_adds_value",
            ]
        )

    comparison["return_delta"] = comparison["cumulative_return_rss"] - comparison["cumulative_return_technical"]
    comparison["sharpe_delta"] = comparison["sharpe_ratio_rss"] - comparison["sharpe_ratio_technical"]
    comparison["drawdown_delta"] = comparison["max_drawdown_rss"] - comparison["max_drawdown_technical"]
    comparison["rss_adds_value"] = (
        (comparison["return_delta"] > 0)
        & (comparison["sharpe_delta"] >= 0)
        & (comparison["drawdown_delta"] >= 0)
    )

    return comparison[
        [
            "validation_period",
            "symbol",
            "return_delta",
            "sharpe_delta",
            "drawdown_delta",
            "rss_adds_value",
        ]
    ]


def rank_strategies_without_raw_return_bias(metrics: pd.DataFrame) -> pd.DataFrame:
    required_columns = {
        "strategy_name",
        "symbol",
        "validation_period",
        "cumulative_return",
        "sharpe_ratio",
        "max_drawdown",
        "trade_count",
    }
    missing_columns = required_columns - set(metrics.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Missing required columns: {missing}")

    ranked = metrics.copy()
    ranked["return_rank"] = ranked.groupby("validation_period")["cumulative_return"].rank(pct=True)
    ranked["sharpe_rank"] = ranked.groupby("validation_period")["sharpe_ratio"].rank(pct=True)
    ranked["drawdown_rank"] = ranked.groupby("validation_period")["max_drawdown"].rank(pct=True)
    ranked["activity_penalty"] = ranked.groupby("validation_period")["trade_count"].rank(pct=True)
    ranked["robust_selection_score"] = (
        0.35 * ranked["return_rank"]
        + 0.35 * ranked["sharpe_rank"]
        + 0.20 * ranked["drawdown_rank"]
        - 0.10 * ranked["activity_penalty"]
    )

    return ranked.sort_values(
        ["validation_period", "robust_selection_score"],
        ascending=[True, False],
    )
