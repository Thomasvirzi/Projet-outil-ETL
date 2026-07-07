import pandas as pd
import pytest

from backtesting.validation import (
    assert_no_test_period_optimization,
    assign_validation_periods,
    measure_rss_filter_contribution,
    rank_strategies_without_raw_return_bias,
    summarize_by_period,
)


def sample_dates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2020-01-02", "2024-06-03", "2025-01-02", "2019-12-31"],
            "symbol": ["GC=F"] * 4,
        }
    )


def sample_metrics() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "validation_period": "test",
                "strategy_name": "moving_average_cross",
                "symbol": "GC=F",
                "cumulative_return": 0.10,
                "sharpe_ratio": 0.8,
                "max_drawdown": -0.20,
                "trade_count": 12,
            },
            {
                "validation_period": "test",
                "strategy_name": "technical_news_filter",
                "symbol": "GC=F",
                "cumulative_return": 0.12,
                "sharpe_ratio": 0.9,
                "max_drawdown": -0.15,
                "trade_count": 8,
            },
            {
                "validation_period": "validation",
                "strategy_name": "moving_average_cross",
                "symbol": "CL=F",
                "cumulative_return": -0.05,
                "sharpe_ratio": -0.2,
                "max_drawdown": -0.25,
                "trade_count": 20,
            },
        ]
    )


def test_assign_validation_periods_uses_project_split() -> None:
    result = assign_validation_periods(sample_dates())

    assert result["validation_period"].tolist() == ["calibration", "validation", "test", "out_of_scope"]
    assert bool(result.loc[result["validation_period"] == "test", "is_optimization_allowed"].iloc[0]) is False


def test_assert_no_test_period_optimization_blocks_final_test() -> None:
    assert_no_test_period_optimization(["calibration", "validation"])

    with pytest.raises(ValueError, match="final test period"):
        assert_no_test_period_optimization(["validation", "test"])


def test_summarize_by_period_measures_stability_by_strategy() -> None:
    summary = summarize_by_period(sample_metrics())

    assert {"validation_period", "strategy_name", "symbols_tested", "positive_symbol_rate"}.issubset(summary.columns)
    test_news = summary[
        (summary["validation_period"] == "test")
        & (summary["strategy_name"] == "technical_news_filter")
    ].iloc[0]
    assert test_news["positive_symbol_rate"] == 1


def test_measure_rss_filter_contribution_compares_against_technical_only() -> None:
    contribution = measure_rss_filter_contribution(sample_metrics())

    assert contribution.iloc[0]["return_delta"] == pytest.approx(0.02)
    assert bool(contribution.iloc[0]["rss_adds_value"]) is True


def test_rank_strategies_without_raw_return_bias_adds_robust_score() -> None:
    ranked = rank_strategies_without_raw_return_bias(sample_metrics())

    assert "robust_selection_score" in ranked.columns
    assert ranked.iloc[0]["validation_period"] in {"test", "validation"}
