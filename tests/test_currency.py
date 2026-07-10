import pandas as pd
import pytest

from scripts.extract_load import currency


def _fake_fx_frame(dates: pd.DatetimeIndex, rate: float) -> pd.DataFrame:
    return pd.DataFrame({"Close": [rate] * len(dates)}, index=dates)


def test_fetch_fx_rate_series_uses_direct_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.date_range("2024-01-01", periods=5, freq="D")

    def fake_download(symbol: str, **_kwargs: object) -> pd.DataFrame:
        assert symbol == "USDEUR=X"
        return _fake_fx_frame(dates, 0.9)

    monkeypatch.setattr(currency.yf, "download", fake_download)

    series = currency.fetch_fx_rate_series("USD", "EUR", start="2024-01-01")

    assert (series == 0.9).all()


def test_fetch_fx_rate_series_falls_back_to_inverse_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.date_range("2024-01-01", periods=5, freq="D")

    def fake_download(symbol: str, **_kwargs: object) -> pd.DataFrame:
        if symbol == "USDEUR=X":
            return pd.DataFrame()
        if symbol == "EURUSD=X":
            return _fake_fx_frame(dates, 1.1)
        raise AssertionError(f"unexpected symbol {symbol}")

    monkeypatch.setattr(currency.yf, "download", fake_download)

    series = currency.fetch_fx_rate_series("USD", "EUR", start="2024-01-01")

    assert series.iloc[0] == pytest.approx(1 / 1.1)


def test_fetch_fx_rate_series_raises_when_no_pair_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(currency.yf, "download", lambda *_a, **_k: pd.DataFrame())

    with pytest.raises(RuntimeError, match="Aucune paire de change"):
        currency.fetch_fx_rate_series("USD", "EUR", start="2024-01-01", max_retries=1)


def test_build_fx_rate_table_reports_errors_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(currency.yf, "download", lambda *_a, **_k: pd.DataFrame())

    rates, errors = currency.build_fx_rate_table({"USD", "EUR"}, "EUR", start="2024-01-01", max_retries=1)

    assert rates == {}
    assert errors and errors[0]["from_currency"] == "USD"


def test_build_fx_rate_table_skips_reference_currency(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    monkeypatch.setattr(currency.yf, "download", lambda symbol, **_k: _fake_fx_frame(dates, 0.9))

    rates, errors = currency.build_fx_rate_table({"EUR"}, "EUR", start="2024-01-01")

    assert rates == {}
    assert errors == []


def test_convert_price_series_to_reference_multiplies_by_rate() -> None:
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    prices = pd.Series([100.0, 101.0, 102.0], index=dates)
    fx_rates = {"USD": pd.Series([0.9, 0.9, 0.9], index=dates)}

    converted = currency.convert_price_series_to_reference(prices, "USD", "EUR", fx_rates)

    assert converted.tolist() == pytest.approx([90.0, 90.9, 91.8])


def test_convert_price_series_same_currency_is_noop() -> None:
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    prices = pd.Series([100.0, 101.0, 102.0], index=dates)

    converted = currency.convert_price_series_to_reference(prices, "EUR", "EUR", {})

    pd.testing.assert_series_equal(converted, prices)


def test_convert_price_series_missing_rate_raises_key_error() -> None:
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    prices = pd.Series([100.0, 101.0, 102.0], index=dates)

    with pytest.raises(KeyError):
        currency.convert_price_series_to_reference(prices, "USD", "EUR", {})
