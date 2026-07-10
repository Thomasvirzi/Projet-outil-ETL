"""FX conversion helpers for the equities pipeline.

The equity universe mixes USD-listed and EUR-listed tickers. Individual backtests are kept
in the local currency of each ticker (no FX assumption baked into a single-asset strategy).
The portfolio-level aggregation (equal-weight / inverse-vol across tickers) needs every price
series expressed in one reference currency before weights and returns can be combined —
otherwise position sizes implicitly mix currencies (e.g. treating 1 USD and 1 EUR as
equivalent units), which silently distorts the weighting.

Conversion method: for every non-reference currency, fetch a daily FX rate series from
Yahoo Finance (`{FROM}{TO}=X`, falling back to the inverse pair `{TO}{FROM}=X` inverted when
Yahoo only lists one direction) and multiply each local-currency price by that day's rate.
Rates are forward-filled onto the price calendar (bounded, like price alignment) since FX
trades on days equity markets are closed.
"""

from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

LOGGER = logging.getLogger(__name__)

FX_SUFFIX = "=X"
DEFAULT_MAX_FORWARD_FILL = 5


def fx_pair_symbol(from_currency: str, to_currency: str) -> str:
    return f"{from_currency}{to_currency}{FX_SUFFIX}"


def _download_fx_series(
    symbol: str,
    start: str,
    end: str | None,
    max_retries: int,
) -> pd.Series:
    @retry(stop=stop_after_attempt(max(1, max_retries)), wait=wait_exponential(multiplier=1, min=1, max=10))
    def _download() -> pd.DataFrame:
        return yf.download(
            symbol,
            start=start,
            end=end,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )

    data = _download()
    if data is None or data.empty:
        return pd.Series(dtype=float)

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    if "Close" not in data.columns:
        return pd.Series(dtype=float)

    series = pd.to_numeric(data["Close"], errors="coerce").dropna()
    series.index = pd.to_datetime(series.index, utc=True, errors="coerce").tz_convert(None)
    series.name = symbol
    return series


def fetch_fx_rate_series(
    from_currency: str,
    to_currency: str,
    start: str,
    end: str | None = None,
    max_retries: int = 3,
) -> pd.Series:
    """Daily rate to convert 1 unit of `from_currency` into `to_currency`.

    Tries the direct Yahoo pair first, then the inverse pair inverted. Raises RuntimeError
    if neither is available so the caller can decide how to degrade (exclude the affected
    ticker from the currency-aware portfolio rather than silently mis-pricing it).
    """
    if from_currency == to_currency:
        raise ValueError("from_currency and to_currency must differ.")

    direct_symbol = fx_pair_symbol(from_currency, to_currency)
    inverse_symbol = fx_pair_symbol(to_currency, from_currency)

    for symbol, invert in ((direct_symbol, False), (inverse_symbol, True)):
        try:
            series = _download_fx_series(symbol, start, end, max_retries)
        except Exception as error:  # noqa: BLE001 - network/library errors are logged and retried elsewhere
            LOGGER.warning("Echec de récupération de la paire FX %s : %s", symbol, error)
            continue

        if series.empty:
            continue

        return (1.0 / series).rename(f"{from_currency}->{to_currency}") if invert else series.rename(
            f"{from_currency}->{to_currency}"
        )

    raise RuntimeError(
        f"Aucune paire de change yfinance disponible pour convertir {from_currency} vers "
        f"{to_currency} (essayé {direct_symbol} et {inverse_symbol})."
    )


def build_fx_rate_table(
    currencies: set[str],
    reference_currency: str,
    start: str,
    end: str | None = None,
    max_retries: int = 3,
) -> tuple[dict[str, pd.Series], list[dict[str, str]]]:
    """Fetch one FX rate series per non-reference currency present in the universe.

    Returns (rates_by_currency, errors). A currency that fails to resolve is omitted from
    `rates_by_currency` and reported in `errors` — callers must exclude the affected tickers
    from currency-aware aggregation rather than guessing a rate.
    """
    rates: dict[str, pd.Series] = {}
    errors: list[dict[str, str]] = []

    for currency in sorted(currencies):
        if currency == reference_currency:
            continue
        try:
            rates[currency] = fetch_fx_rate_series(
                currency, reference_currency, start=start, end=end, max_retries=max_retries
            )
        except Exception as error:  # noqa: BLE001 - collected as a data-quality error, not fatal
            LOGGER.error("Conversion %s -> %s indisponible : %s", currency, reference_currency, error)
            errors.append(
                {
                    "from_currency": currency,
                    "to_currency": reference_currency,
                    "error": str(error),
                }
            )

    return rates, errors


def convert_price_series_to_reference(
    prices: pd.Series,
    currency: str,
    reference_currency: str,
    fx_rates: dict[str, pd.Series],
    max_forward_fill: int = DEFAULT_MAX_FORWARD_FILL,
) -> pd.Series:
    """Convert a local-currency price series into the reference currency.

    FX rates are aligned onto the price calendar with a bounded forward-fill (FX markets
    trade when some equity markets are closed), never a backward-fill, so no future
    information leaks into a conversion.
    """
    if currency == reference_currency:
        return prices.copy()

    if currency not in fx_rates:
        raise KeyError(
            f"No FX rate available to convert {currency} into {reference_currency}. "
            "Call build_fx_rate_table first and exclude tickers with missing currencies."
        )

    rate = fx_rates[currency]
    aligned_rate = rate.reindex(prices.index.union(rate.index)).sort_index().ffill(limit=max_forward_fill)
    aligned_rate = aligned_rate.reindex(prices.index)
    converted = prices * aligned_rate
    converted.name = prices.name
    return converted
