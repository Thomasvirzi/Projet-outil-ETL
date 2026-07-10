from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.extract_load import equities_trading as et

UNIVERSE = [
    {"equity_id": "AAPL", "ticker": "AAPL", "name": "Apple", "currency": "USD", "exchange": "NASDAQ", "enabled": True},
    {"equity_id": "ASML", "ticker": "ASML.AS", "name": "ASML", "currency": "EUR", "exchange": "Euronext Amsterdam", "enabled": True},
]


def _row(date: str, symbol: str = "AAA", **overrides: object) -> dict[str, object]:
    row = {
        "date": date,
        "symbol": symbol,
        "equity_id": symbol,
        "name": symbol,
        "currency": "USD",
        "exchange": "NASDAQ",
        "open": 10.0,
        "high": 10.5,
        "low": 9.5,
        "close": 10.0,
        "adjusted_close": 10.0,
        "volume": 1_000.0,
        "dividends": 0.0,
        "stock_splits": 0.0,
        "source": "yahoo_finance",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# select_equities
# ---------------------------------------------------------------------------

def test_select_equities_returns_full_universe_when_no_filter() -> None:
    assert et.select_equities(UNIVERSE, None) == UNIVERSE


def test_select_equities_filters_by_ticker() -> None:
    result = et.select_equities(UNIVERSE, ["ASML.AS"])

    assert [equity["ticker"] for equity in result] == ["ASML.AS"]


def test_select_equities_rejects_unknown_ticker_without_substitution() -> None:
    with pytest.raises(ValueError, match="TSLA"):
        et.select_equities(UNIVERSE, ["TSLA"])


# ---------------------------------------------------------------------------
# ticker validation
# ---------------------------------------------------------------------------

def test_probe_ticker_is_valid_when_close_data_available(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.date_range("2024-01-01", periods=5, freq="B")
    frame = pd.DataFrame({"Close": [10, 11, 12, 13, 14]}, index=dates)
    monkeypatch.setattr(et.yf, "download", lambda *_a, **_k: frame)

    result = et.probe_ticker("AAPL", max_retries=1)

    assert result["valid"] is True
    assert result["rows"] == 5
    assert result["error"] is None


def test_probe_ticker_is_invalid_on_empty_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(et.yf, "download", lambda *_a, **_k: pd.DataFrame())

    result = et.probe_ticker("FAKE", max_retries=1)

    assert result["valid"] is False
    assert result["error"]


def test_probe_ticker_is_invalid_after_exhausted_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    def always_fail(*_a: object, **_k: object) -> pd.DataFrame:
        raise RuntimeError("network down")

    monkeypatch.setattr(et.yf, "download", always_fail)
    monkeypatch.setattr(et.time, "sleep", lambda *_a: None)

    result = et.probe_ticker("FAKE", max_retries=2)

    assert result["valid"] is False
    assert "network down" in result["error"]


def test_validate_tickers_isolates_failures_without_interrupting_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_download(ticker: str, **_kwargs: object) -> pd.DataFrame:
        if ticker == "AAPL":
            dates = pd.date_range("2024-01-01", periods=5, freq="B")
            return pd.DataFrame({"Close": [1, 2, 3, 4, 5]}, index=dates)
        return pd.DataFrame()

    monkeypatch.setattr(et.yf, "download", fake_download)
    monkeypatch.setattr(et.time, "sleep", lambda *_a: None)

    valid, invalid, validation_df = et.validate_tickers(UNIVERSE, max_retries=1)

    assert [equity["ticker"] for equity in valid] == ["AAPL"]
    assert [equity["ticker"] for equity in invalid] == ["ASML.AS"]
    assert len(validation_df) == 2


# ---------------------------------------------------------------------------
# clean_equity_prices
# ---------------------------------------------------------------------------

def test_clean_equity_prices_rejects_non_positive_prices_without_futures_carveout() -> None:
    # Symbol deliberately named like the WTI futures ticker to prove there is no CL=F
    # carve-out here (unlike ingest_commodities.clean_market_data), since negative equity
    # prices can never be legitimate.
    frame = pd.DataFrame(
        [
            _row("2024-01-01", symbol="CL=F", open=-5.0, high=-1.0, low=-10.0, close=-3.0, adjusted_close=-3.0),
            _row("2024-01-02", symbol="CL=F", close=10.5, adjusted_close=10.5),
        ]
    )

    cleaned, quality = et.clean_equity_prices([frame])

    assert len(cleaned) == 1
    assert cleaned.iloc[0]["close"] == 10.5
    assert quality.iloc[0]["non_positive_price_rows_dropped"] == 1


def test_clean_equity_prices_does_not_forward_fill_missing_trading_days() -> None:
    frame = pd.DataFrame(
        [
            _row("2024-01-01", close=10.0, adjusted_close=10.0),
            _row("2024-01-05", close=12.0, adjusted_close=12.0),
        ]
    )

    cleaned, _quality = et.clean_equity_prices([frame])

    assert cleaned["date"].tolist() == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-05")]


def test_clean_equity_prices_fixes_ohlc_inconsistency() -> None:
    frame = pd.DataFrame([_row("2024-01-01", open=10.0, high=9.0, low=11.0, close=10.0, adjusted_close=10.0)])

    cleaned, quality = et.clean_equity_prices([frame])

    row = cleaned.iloc[0]
    assert row["high"] >= max(row["open"], row["low"], row["close"])
    assert row["low"] <= min(row["open"], row["high"], row["close"])
    assert quality.iloc[0]["ohlc_inconsistent_rows_fixed"] == 1


def test_clean_equity_prices_removes_duplicate_dates_keeping_last() -> None:
    frame = pd.DataFrame(
        [
            _row("2024-01-01", close=10.0, adjusted_close=10.0),
            _row("2024-01-01", close=11.0, adjusted_close=11.0),
        ]
    )

    cleaned, quality = et.clean_equity_prices([frame])

    assert len(cleaned) == 1
    assert cleaned.iloc[0]["close"] == 11.0
    assert quality.iloc[0]["duplicate_dates_removed"] == 1


def test_clean_equity_prices_returns_empty_frames_for_no_input() -> None:
    cleaned, quality = et.clean_equity_prices([])

    assert cleaned.empty
    assert quality.empty


# ---------------------------------------------------------------------------
# backtests (Buy & Hold baseline, no look-ahead)
# ---------------------------------------------------------------------------

def _indicator_ready_frame(symbol: str = "AAA", n: int = 5) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    prices = np.linspace(100, 100 + n, n)
    frame = pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "close": prices,
            "adjusted_close": prices,
            "high": prices * 1.01,
            "low": prices * 0.99,
            "volume": 1000.0,
        }
    )
    return et.attach_indicators(frame)


def test_run_ticker_backtests_always_includes_buy_and_hold_baseline() -> None:
    data = _indicator_ready_frame()
    engine_kwargs = {"initial_capital": 1_000.0, "fee_rate": 0.0, "slippage_rate": 0.0, "allow_short": False}

    rows, _trades, curves = et.run_ticker_backtests(data, "AAA", ["buy_and_hold"], engine_kwargs)

    assert rows[0]["strategy_name"] == "buy_and_hold"
    assert "Buy & Hold" in curves["series_name"].tolist()


def test_run_ticker_backtests_shifts_signal_no_execution_on_first_day() -> None:
    data = _indicator_ready_frame()
    engine_kwargs = {"initial_capital": 1_000.0, "fee_rate": 0.0, "slippage_rate": 0.0, "allow_short": False}

    _rows, trades, _curves = et.run_ticker_backtests(data, "AAA", ["buy_and_hold"], engine_kwargs)

    # Buy & Hold enters on day 2 at the earliest (signal generated day 1, executed day 2):
    # no look-ahead, no same-day execution of a same-day signal.
    assert trades.iloc[0]["date"] == pd.to_datetime(data["date"].iloc[1]).date()


def test_run_ticker_backtests_flags_insufficient_history_for_indicator_strategies() -> None:
    data = _indicator_ready_frame(n=5)  # far fewer than the 60-row minimum
    engine_kwargs = {"initial_capital": 1_000.0, "fee_rate": 0.0, "slippage_rate": 0.0, "allow_short": False}

    rows, _trades, _curves = et.run_ticker_backtests(data, "AAA", ["moving_average_cross"], engine_kwargs)

    assert rows[0]["insufficient_history"] is True


# ---------------------------------------------------------------------------
# portfolio construction
# ---------------------------------------------------------------------------

def test_apply_cash_reserve_scales_returns_and_recomputes_level() -> None:
    index_df = pd.DataFrame({"daily_return": [np.nan, 0.10, -0.05], "index_level": [100.0, 110.0, 104.5]})

    adjusted = et.apply_cash_reserve(index_df, cash_reserve=0.5, base_value=100.0)

    assert adjusted["daily_return"].iloc[1] == pytest.approx(0.05)
    assert adjusted["index_level"].iloc[1] == pytest.approx(105.0)


def test_apply_cash_reserve_is_noop_when_reserve_is_zero() -> None:
    index_df = pd.DataFrame({"daily_return": [0.0, 0.1], "index_level": [100.0, 110.0]})

    result = et.apply_cash_reserve(index_df, cash_reserve=0.0, base_value=100.0)

    assert result is index_df


def test_build_local_currency_no_fx_portfolio_averages_returns_across_tickers() -> None:
    dates = pd.date_range("2024-01-01", periods=3, freq="B")
    cleaned = pd.DataFrame(
        [
            {"date": dates[0], "symbol": "AAA", "adjusted_close": 100.0},
            {"date": dates[1], "symbol": "AAA", "adjusted_close": 110.0},
            {"date": dates[2], "symbol": "AAA", "adjusted_close": 121.0},
            {"date": dates[0], "symbol": "BBB", "adjusted_close": 50.0},
            {"date": dates[1], "symbol": "BBB", "adjusted_close": 45.0},
            {"date": dates[2], "symbol": "BBB", "adjusted_close": 49.5},
        ]
    )
    equities = [{"ticker": "AAA"}, {"ticker": "BBB"}]

    result = et.build_local_currency_no_fx_portfolio(cleaned, equities, base_value=100.0)

    assert result.iloc[0]["index_level"] == pytest.approx(100.0)
    assert result.iloc[1]["index_level"] == pytest.approx(100.0)  # +10% / -10% average out
    assert result.iloc[2]["index_level"] == pytest.approx(110.0)  # +10% / +10%


def test_build_equity_portfolio_requires_at_least_two_tickers() -> None:
    panel = pd.DataFrame({"AAA": [100.0, 101.0]}, index=pd.date_range("2024-01-01", periods=2, freq="B"))
    args = SimpleNamespace(
        max_positions=20,
        allocation="equal",
        rebalance="none",
        vol_lookback=5,
        min_vol_observations=2,
        transaction_cost_bps=0.0,
        max_forward_fill=2,
        max_position_weight=0.5,
        cash_reserve=0.0,
    )

    with pytest.raises(ValueError, match="deux actions"):
        et.build_equity_portfolio(panel, {"AAA": {"name": "Apple"}}, args)


def test_build_equity_portfolio_equal_weight_sums_to_one() -> None:
    dates = pd.date_range("2024-01-01", periods=5, freq="B")
    panel = pd.DataFrame(
        {
            "AAA": [100.0, 101.0, 102.0, 103.0, 104.0],
            "BBB": [50.0, 51.0, 52.0, 53.0, 54.0],
            "CCC": [20.0, 21.0, 22.0, 23.0, 24.0],
            "DDD": [10.0, 10.5, 11.0, 11.5, 12.0],
        },
        index=dates,
    )
    equities_by_ticker = {ticker: {"name": ticker} for ticker in panel.columns}
    args = SimpleNamespace(
        max_positions=20,
        allocation="equal",
        rebalance="none",
        vol_lookback=5,
        min_vol_observations=2,
        transaction_cost_bps=0.0,
        max_forward_fill=1,
        max_position_weight=0.4,
        cash_reserve=0.0,
    )

    index_df, weights_df = et.build_equity_portfolio(panel, equities_by_ticker, args)

    first_date_weights = weights_df[weights_df["date"] == weights_df["date"].min()]
    assert first_date_weights["actual_weight"].sum() == pytest.approx(1.0)
    assert index_df["index_level"].iloc[0] == pytest.approx(100.0)
