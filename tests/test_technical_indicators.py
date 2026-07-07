from pathlib import Path


TECHNICAL_INDICATORS_SQL = Path("dbt_finance/models/warehouse/int_technical_indicators.sql")


def test_technical_indicator_model_contains_step_10_outputs() -> None:
    sql = TECHNICAL_INDICATORS_SQL.read_text(encoding="utf-8")

    expected_outputs = [
        "simple_return",
        "log_return",
        "sma_20",
        "sma_50",
        "rsi_14",
        "stochastic_rsi_k",
        "stochastic_rsi_d",
        "macd",
        "macd_signal",
        "atr_14",
        "historical_volatility_20d",
        "sma_100",
        "sma_200",
        "bollinger_upper_20d",
        "bollinger_lower_20d",
        "volume_ratio_20d",
    ]

    for output in expected_outputs:
        assert output in sql


def test_technical_indicator_windows_do_not_look_ahead() -> None:
    sql = TECHNICAL_INDICATORS_SQL.read_text(encoding="utf-8").lower()

    assert "following" not in sql
    assert "preceding and current row" in sql
    assert "lag(close)" in sql
