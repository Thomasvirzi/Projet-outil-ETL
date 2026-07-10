#!/usr/bin/env python3
"""
Pipeline de trading sur un univers d'actions, adaptée de la pipeline matières premières.

Réutilise directement :
- backtesting.engine.BacktestEngine, backtesting.strategies.* et backtesting.costs
  (aucune logique de roll/contango/backwardation/livraison physique n'y existe déjà, donc
  rien à retirer pour des actions) ;
- backtesting.metrics.summarize_result / compare_backtest_results ;
- scripts.extract_load.commodity_benchmark_index.{align_price_panel, build_synthetic_index,
  build_buy_and_hold_indices, calculate_series_metrics, save_csv_atomic, save_json_atomic,
  IndexConfig} — le même pattern d'import que scripts/extract_load/ingest_benchmarks.py ;
- scripts.extract_load.ingest_commodities.get_default_yfinance_end_date.

N'est PAS une réutilisation brute de scripts.extract_load.ingest_commodities.clean_market_data :
cette fonction contient une exception spécifique aux futures (prix négatif toléré pour
CL=F, l'épisode du WTI en avril 2020), qui n'a pas de sens pour des actions. clean_equity_prices
ci-dessous reprend la même logique de nettoyage (tri, dédoublonnage, DatetimeIndex, pas de
forward-fill, cohérence OHLC) mais rejette strictement tout prix nul ou négatif.

Exemple :
    python scripts/extract_load/equities_trading.py \\
        --start 2015-01-01 --end 2026-01-01 --capital 10000 \\
        --commission 0.001 --slippage 0.0005 --rebalance monthly

    python scripts/extract_load/equities_trading.py --tickers AAPL NVDA ASML.AS
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yfinance as yf

try:
    from backtesting.engine import BacktestEngine
    from backtesting.indicators import compute_technical_indicators
    from backtesting.metrics import extended_trade_metrics, summarize_result
    from backtesting.models import BacktestConfig
    from backtesting.strategies import (
        BreakoutStrategy,
        BuyAndHoldStrategy,
        MovingAverageCrossStrategy,
        MovingAverageStochRsiStrategy,
        Strategy,
        TechnicalNewsFilterStrategy,
    )
    from scripts.extract_load.commodity_benchmark_index import (
        IndexConfig,
        align_price_panel,
        build_synthetic_index,
        calculate_series_metrics,
        save_csv_atomic,
        save_json_atomic,
    )
    from scripts.extract_load.config import ProjectConfig, load_project_config
    from scripts.extract_load.currency import build_fx_rate_table, convert_price_series_to_reference
    from scripts.extract_load.ingest_commodities import get_default_yfinance_end_date
    from scripts.extract_load import equities_visuals as visuals
except ModuleNotFoundError:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from backtesting.engine import BacktestEngine
    from backtesting.indicators import compute_technical_indicators
    from backtesting.metrics import extended_trade_metrics, summarize_result
    from backtesting.models import BacktestConfig
    from backtesting.strategies import (
        BreakoutStrategy,
        BuyAndHoldStrategy,
        MovingAverageCrossStrategy,
        MovingAverageStochRsiStrategy,
        Strategy,
        TechnicalNewsFilterStrategy,
    )
    from scripts.extract_load.commodity_benchmark_index import (
        IndexConfig,
        align_price_panel,
        build_synthetic_index,
        calculate_series_metrics,
        save_csv_atomic,
        save_json_atomic,
    )
    from scripts.extract_load.config import ProjectConfig, load_project_config
    from scripts.extract_load.currency import build_fx_rate_table, convert_price_series_to_reference
    from scripts.extract_load.ingest_commodities import get_default_yfinance_end_date
    from scripts.extract_load import equities_visuals as visuals


LOGGER = logging.getLogger(__name__)

DEFAULT_START_DATE = "2015-01-01"
DEFAULT_INTERVAL = "1d"
DEFAULT_OUTPUT_DIR = "outputs/equities"
MIN_ROWS_FOR_INDICATOR_STRATEGIES = 60
NUMERIC_COLUMNS = ["open", "high", "low", "close", "adjusted_close", "volume", "dividends", "stock_splits"]

STRATEGY_FACTORIES: dict[str, Callable[[], Strategy]] = {
    "buy_and_hold": BuyAndHoldStrategy,
    "moving_average_cross": MovingAverageCrossStrategy,
    "moving_average_stoch_rsi": MovingAverageStochRsiStrategy,
    "technical_news_filter": TechnicalNewsFilterStrategy,
    "breakout_20d": BreakoutStrategy,
}
# breakout_20d computes its own rolling high/low directly from `close` and needs no
# precomputed indicator columns; buy_and_hold needs nothing either.
INDICATOR_FREE_STRATEGIES = {"buy_and_hold", "breakout_20d"}


@dataclass(frozen=True)
class PipelineErrors:
    rows: list[dict[str, Any]]

    def add(self, stage: str, symbol: str | None, error: str) -> None:
        self.rows.append({"stage": stage, "symbol": symbol, "error": error, "logged_at": datetime.now(UTC).isoformat()})


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest un univers d'actions (yfinance) avec les stratégies déjà implémentées."
    )
    parser.add_argument("--start", default=DEFAULT_START_DATE, help="Date de début YYYY-MM-DD.")
    parser.add_argument("--end", default=None, help="Date de fin YYYY-MM-DD. Défaut : aujourd'hui.")
    parser.add_argument("--interval", default=DEFAULT_INTERVAL, help="Intervalle yfinance. Défaut : 1d.")
    parser.add_argument("--tickers", nargs="*", default=None, help="Sous-ensemble de tickers à tester, ex. AAPL NVDA ASML.AS.")
    parser.add_argument(
        "--strategy",
        default="all",
        choices=[*STRATEGY_FACTORIES, "all"],
        help="Stratégie à exécuter. 'all' exécute les 5 stratégies existantes.",
    )
    parser.add_argument("--capital", type=float, default=10_000.0, help="Capital initial par backtest individuel.")
    parser.add_argument("--commission", type=float, default=0.001, help="Taux de commission (fee_rate).")
    parser.add_argument("--slippage", type=float, default=0.0005, help="Taux de slippage.")
    parser.add_argument("--allow-short", action="store_true", help="Autorise les positions courtes (interdites par défaut).")
    parser.add_argument(
        "--rebalance",
        default="monthly",
        choices=["none", "monthly", "quarterly", "annual"],
        help="Fréquence de rebalancement du portefeuille equal-weight. Défaut : monthly.",
    )
    parser.add_argument("--allocation", default="equal", choices=["equal", "inverse_vol"], help="Méthode d'allocation du portefeuille.")
    parser.add_argument("--max-position-weight", type=float, default=0.15, help="Plafond de poids par position dans le portefeuille.")
    parser.add_argument("--max-positions", type=int, default=20, help="Nombre maximal de positions simultanées dans le portefeuille.")
    parser.add_argument("--cash-reserve", type=float, default=0.0, help="Fraction du portefeuille conservée en cash (rendement nul).")
    parser.add_argument("--vol-lookback", type=int, default=60, help="Fenêtre de volatilité pour l'allocation inverse_vol.")
    parser.add_argument("--min-vol-observations", type=int, default=20, help="Observations minimales pour estimer la volatilité.")
    parser.add_argument("--transaction-cost-bps", type=float, default=0.0, help="Coût de rebalancement du portefeuille, en points de base.")
    parser.add_argument("--reference-currency", default="EUR", help="Devise de référence du portefeuille agrégé. Défaut : EUR.")
    parser.add_argument("--market-benchmark", default="SPY", help="Ticker Yahoo Finance du benchmark de marché. Défaut : SPY.")
    parser.add_argument("--max-retries", type=int, default=3, help="Tentatives yfinance par ticker en cas d'échec.")
    parser.add_argument("--request-delay-seconds", type=float, default=1.0, help="Délai entre deux téléchargements yfinance.")
    parser.add_argument("--max-forward-fill", type=int, default=2, help="Report borné du dernier prix connu pour aligner les calendriers du portefeuille.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Dossier d'export. Défaut : outputs/equities.")
    parser.add_argument("--dry-run", action="store_true", help="Valide l'univers et affiche la sélection sans télécharger l'historique complet.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Niveau de log.")
    return parser.parse_args()


def configure_logging(level: str, log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    return log_path


# ============================================================
# UNIVERS ET VALIDATION DES TICKERS
# ============================================================

def load_equity_universe(config: ProjectConfig) -> list[dict[str, Any]]:
    equities = config.equities.get("equities", [])
    return [equity for equity in equities if equity.get("enabled", True)]


def select_equities(universe: list[dict[str, Any]], tickers: list[str] | None) -> list[dict[str, Any]]:
    if not tickers:
        return universe

    by_ticker = {equity["ticker"]: equity for equity in universe}
    unknown = [ticker for ticker in tickers if ticker not in by_ticker]
    if unknown:
        raise ValueError(
            "Tickers absents de config/equities.yml (aucune substitution silencieuse) : "
            + ", ".join(unknown)
        )
    return [by_ticker[ticker] for ticker in tickers]


def _with_retries(func: Callable[[], pd.DataFrame], max_retries: int) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(1, max(1, max_retries) + 1):
        try:
            return func()
        except Exception as error:  # noqa: BLE001 - network/library errors, retried below
            last_error = error
            LOGGER.warning("Tentative %s/%s échouée : %s", attempt, max_retries, error)
            if attempt < max_retries:
                time.sleep(min(2**attempt, 10))
    assert last_error is not None
    raise last_error


def _flatten_columns(data: pd.DataFrame) -> pd.DataFrame:
    if isinstance(data.columns, pd.MultiIndex):
        data = data.copy()
        data.columns = data.columns.get_level_values(0)
    return data


def probe_ticker(ticker: str, max_retries: int) -> dict[str, Any]:
    def _probe() -> pd.DataFrame:
        return yf.download(ticker, period="5d", interval="1d", auto_adjust=False, progress=False, threads=False)

    try:
        data = _with_retries(_probe, max_retries)
    except Exception as error:  # noqa: BLE001 - reported as an invalid ticker, not fatal
        return {"ticker": ticker, "valid": False, "rows": 0, "first_date": None, "last_date": None, "error": str(error)}

    data = _flatten_columns(data)
    if data is None or data.empty or "Close" not in data.columns or data["Close"].dropna().empty:
        return {
            "ticker": ticker,
            "valid": False,
            "rows": 0 if data is None else int(len(data)),
            "first_date": None,
            "last_date": None,
            "error": "Aucune donnée OHLCV exploitable retournée par yfinance.",
        }

    return {
        "ticker": ticker,
        "valid": True,
        "rows": int(len(data)),
        "first_date": data.index.min(),
        "last_date": data.index.max(),
        "error": None,
    }


def validate_tickers(
    equities: list[dict[str, Any]],
    max_retries: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], pd.DataFrame]:
    rows = []
    for equity in equities:
        probe = probe_ticker(equity["ticker"], max_retries)
        rows.append(
            {
                **probe,
                "equity_id": equity["equity_id"],
                "name": equity["name"],
                "currency": equity["currency"],
                "exchange": equity.get("exchange"),
            }
        )

    validation_df = pd.DataFrame(rows)
    valid_tickers = {row["ticker"] for row in rows if row["valid"]}
    valid_equities = [equity for equity in equities if equity["ticker"] in valid_tickers]
    invalid_equities = [equity for equity in equities if equity["ticker"] not in valid_tickers]

    LOGGER.info(
        "Validation des tickers : %s valides, %s invalides.",
        len(valid_equities),
        len(invalid_equities),
    )
    if valid_equities:
        LOGGER.info("Valides : %s", ", ".join(equity["ticker"] for equity in valid_equities))
    if invalid_equities:
        LOGGER.warning("Invalides (ignorés, non substitués) : %s", ", ".join(equity["ticker"] for equity in invalid_equities))

    return valid_equities, invalid_equities, validation_df


# ============================================================
# TÉLÉCHARGEMENT ET NETTOYAGE
# ============================================================

def download_equity_history(
    ticker: str,
    start: str,
    end: str | None,
    interval: str,
    max_retries: int,
) -> pd.DataFrame:
    def _download() -> pd.DataFrame:
        return yf.download(
            ticker,
            start=start,
            end=end,
            interval=interval,
            auto_adjust=False,
            actions=True,
            progress=False,
            threads=False,
        )

    data = _with_retries(_download, max_retries)
    data = _flatten_columns(data)
    if data is None or data.empty:
        raise ValueError(f"Aucune donnée retournée par yfinance pour {ticker}.")
    return data


def normalize_equity_frame(raw: pd.DataFrame, equity: dict[str, Any]) -> pd.DataFrame:
    frame = raw.reset_index()
    frame.columns = [str(column).strip().lower().replace(" ", "_") for column in frame.columns]

    if "date" not in frame.columns and "index" in frame.columns:
        frame = frame.rename(columns={"index": "date"})
    if "datetime" in frame.columns and "date" not in frame.columns:
        frame = frame.rename(columns={"datetime": "date"})
    frame = frame.rename(columns={"adj_close": "adjusted_close"})

    for column in ("dividends", "stock_splits"):
        if column not in frame.columns:
            frame[column] = 0.0

    frame["symbol"] = equity["ticker"]
    frame["equity_id"] = equity["equity_id"]
    frame["name"] = equity["name"]
    frame["currency"] = equity["currency"]
    frame["exchange"] = equity.get("exchange")
    frame["source"] = "yahoo_finance"
    return frame


def clean_equity_prices(frames: list[pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Adapted from ingest_commodities.clean_market_data, without the CL=F negative-price
    carve-out (a futures-specific hypothesis that does not apply to equities): any
    non-positive OHLC price is rejected outright, never tolerated.
    """
    if not frames:
        return pd.DataFrame(), pd.DataFrame()

    raw = pd.concat(frames, ignore_index=True)
    cleaned_frames = []
    quality_rows = []

    for symbol, group in raw.groupby("symbol"):
        rows_downloaded = len(group)
        working = group.copy()
        working["date"] = pd.to_datetime(working["date"], utc=True, errors="coerce").dt.tz_convert(None).dt.normalize()
        working = working.dropna(subset=["date"])

        for column in NUMERIC_COLUMNS:
            if column in working:
                working[column] = pd.to_numeric(working[column], errors="coerce")
                working[column] = working[column].replace([float("inf"), float("-inf")], pd.NA)

        working = working.sort_values("date")
        duplicate_dates_removed = int(working.duplicated(subset=["date"]).sum())
        working = working.drop_duplicates(subset=["date"], keep="last")

        core_columns = [column for column in ("open", "high", "low", "close", "adjusted_close") if column in working]
        empty_mask = working[core_columns].isna().all(axis=1) if core_columns else pd.Series(False, index=working.index)
        empty_rows_dropped = int(empty_mask.sum())
        working = working.loc[~empty_mask]

        missing_counts = {
            f"{column}_missing": int(working[column].isna().sum())
            for column in NUMERIC_COLUMNS
            if column in working
        }

        working = working.dropna(subset=[column for column in ("close", "adjusted_close") if column in working])

        price_columns = [column for column in ("open", "high", "low", "close", "adjusted_close") if column in working]
        non_positive_mask = (working[price_columns] <= 0).any(axis=1) if price_columns else pd.Series(False, index=working.index)
        non_positive_price_rows_dropped = int(non_positive_mask.sum())
        working = working.loc[~non_positive_mask]

        ohlc_inconsistent_rows_fixed = 0
        if {"open", "high", "low", "close"}.issubset(working.columns):
            ohlc_columns = ["open", "high", "low", "close"]
            inconsistent_mask = (working["high"] < working[ohlc_columns].max(axis=1)) | (
                working["low"] > working[ohlc_columns].min(axis=1)
            )
            ohlc_inconsistent_rows_fixed = int(inconsistent_mask.sum())
            working["high"] = working[ohlc_columns].max(axis=1)
            working["low"] = working[ohlc_columns].min(axis=1)

        if "dividends" in working:
            working["dividends"] = working["dividends"].fillna(0.0)
        if "stock_splits" in working:
            working["stock_splits"] = working["stock_splits"].fillna(0.0)
        working["ingested_at"] = datetime.now(UTC).isoformat()

        cleaned_frames.append(working)
        quality_rows.append(
            {
                "symbol": symbol,
                "rows_downloaded": rows_downloaded,
                "rows_after_cleaning": len(working),
                "duplicate_dates_removed": duplicate_dates_removed,
                "empty_rows_dropped": empty_rows_dropped,
                "non_positive_price_rows_dropped": non_positive_price_rows_dropped,
                "ohlc_inconsistent_rows_fixed": ohlc_inconsistent_rows_fixed,
                "first_date": working["date"].min() if not working.empty else None,
                "last_date": working["date"].max() if not working.empty else None,
                **missing_counts,
            }
        )

    cleaned = pd.concat(cleaned_frames, ignore_index=True) if cleaned_frames else pd.DataFrame()
    if not cleaned.empty:
        column_order = [
            "date", "symbol", "equity_id", "name", "exchange", "currency",
            "open", "high", "low", "close", "adjusted_close", "volume",
            "dividends", "stock_splits", "source", "ingested_at",
        ]
        cleaned = (
            cleaned[[column for column in column_order if column in cleaned.columns]]
            .sort_values(["symbol", "date"])
            .reset_index(drop=True)
        )

    return cleaned, pd.DataFrame(quality_rows)


# ============================================================
# INDICATEURS ET BACKTESTS INDIVIDUELS
# ============================================================

def attach_indicators(cleaned: pd.DataFrame) -> pd.DataFrame:
    """Indicators are computed on adjusted_close, not raw close, so a stock split does not
    show up as a fake trend break in sma_20/sma_50/rsi_14."""
    return compute_technical_indicators(cleaned, price_column="adjusted_close")


def run_ticker_backtests(
    indicator_data: pd.DataFrame,
    symbol: str,
    strategy_names: list[str],
    engine_config_kwargs: dict[str, Any],
) -> tuple[list[dict[str, Any]], pd.DataFrame, pd.DataFrame]:
    symbol_data = (
        indicator_data.loc[indicator_data["symbol"] == symbol]
        .sort_values("date")
        .reset_index(drop=True)
    )
    if symbol_data.empty:
        return [], pd.DataFrame(), pd.DataFrame()

    # Backtests are executed on adjusted_close so dividends and splits are reflected both
    # in the signal (via indicators computed on adjusted_close) and in the executed P&L.
    engine_input = symbol_data.copy()
    engine_input["close"] = engine_input["adjusted_close"]

    has_enough_history = (
        len(symbol_data) >= MIN_ROWS_FOR_INDICATOR_STRATEGIES
        and "sma_50" in symbol_data
        and symbol_data["sma_50"].notna().any()
    )

    buy_hold_config = BacktestConfig(strategy_name="buy_and_hold", **engine_config_kwargs)
    buy_hold_engine = BacktestEngine(buy_hold_config)
    buy_hold_result = buy_hold_engine.run(engine_input, BuyAndHoldStrategy())
    buy_hold_frames = buy_hold_engine.result_to_frames(buy_hold_result)
    buy_hold_daily = buy_hold_frames["daily_portfolio"]
    buy_hold_returns = (
        buy_hold_daily.set_index("date")["equity"].pct_change().fillna(0)
        if not buy_hold_daily.empty
        else pd.Series(dtype=float)
    )

    summary_rows: list[dict[str, Any]] = []
    trade_frames: list[pd.DataFrame] = []
    curve_frames: list[pd.DataFrame] = []

    for strategy_name in strategy_names:
        if (
            strategy_name not in INDICATOR_FREE_STRATEGIES
            and strategy_name != "buy_and_hold"
            and not has_enough_history
        ):
            summary_rows.append(
                {
                    "symbol": symbol,
                    "strategy_name": strategy_name,
                    "insufficient_history": True,
                    "rows_available": len(symbol_data),
                }
            )
            continue

        if strategy_name == "buy_and_hold":
            result, frames = buy_hold_result, buy_hold_frames
        else:
            config = BacktestConfig(strategy_name=strategy_name, **engine_config_kwargs)
            engine = BacktestEngine(config)
            strategy = STRATEGY_FACTORIES[strategy_name]()
            result = engine.run(engine_input, strategy)
            frames = engine.result_to_frames(result)

        summary = summarize_result(result, benchmark_returns=buy_hold_returns)
        extended = extended_trade_metrics(frames["trades"], frames["daily_portfolio"])
        summary_rows.append({"insufficient_history": False, **summary, **extended})

        trades = frames["trades"].copy()
        if not trades.empty:
            trades["strategy_name"] = strategy_name
            trades["symbol"] = symbol
            trade_frames.append(trades)

        daily = frames["daily_portfolio"].copy()
        if not daily.empty:
            curve = daily[["date", "equity"]].copy()
            curve["symbol"] = symbol
            curve["series_name"] = "Buy & Hold" if strategy_name == "buy_and_hold" else strategy_name
            curve["series_type"] = "buy_hold" if strategy_name == "buy_and_hold" else "strategy"
            curve_frames.append(curve)

    trades_df = pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame()
    curves_df = pd.concat(curve_frames, ignore_index=True) if curve_frames else pd.DataFrame()
    return summary_rows, trades_df, curves_df


def run_all_backtests(
    indicator_data: pd.DataFrame,
    valid_equities: list[dict[str, Any]],
    strategy_names: list[str],
    engine_config_kwargs: dict[str, Any],
    errors: PipelineErrors,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary_rows: list[dict[str, Any]] = []
    trade_frames: list[pd.DataFrame] = []
    curve_frames: list[pd.DataFrame] = []

    for equity in valid_equities:
        symbol = equity["ticker"]
        try:
            rows, trades_df, curves_df = run_ticker_backtests(
                indicator_data, symbol, strategy_names, engine_config_kwargs
            )
        except Exception as error:  # noqa: BLE001 - one ticker's failure must not stop the run
            LOGGER.exception("Backtest impossible pour %s", symbol)
            errors.add("backtest", symbol, str(error))
            continue

        summary_rows.extend(rows)
        if not trades_df.empty:
            trade_frames.append(trades_df)
        if not curves_df.empty:
            curve_frames.append(curves_df)

    individual_backtests = pd.DataFrame(summary_rows)
    trades = pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame()
    curves = pd.concat(curve_frames, ignore_index=True) if curve_frames else pd.DataFrame()
    return individual_backtests, trades, curves


# ============================================================
# BENCHMARKS : BUY & HOLD PAR ACTION, MARCHÉ
# ============================================================

def compute_individual_buy_hold_benchmarks(
    cleaned: pd.DataFrame,
    valid_equities: list[dict[str, Any]],
    base_value: float,
) -> pd.DataFrame:
    """Each ticker's own Buy & Hold, from its own first available date — deliberately not
    aligned to the whole universe's common calendar (align_price_panel is reserved for the
    multi-asset portfolio, where a shared calendar is actually meaningful)."""
    rows = []
    for equity in valid_equities:
        symbol = equity["ticker"]
        series = (
            cleaned.loc[cleaned["symbol"] == symbol]
            .set_index("date")["adjusted_close"]
            .sort_index()
            .pipe(pd.to_numeric, errors="coerce")
            .dropna()
        )
        if series.empty or series.iloc[0] <= 0:
            continue

        rebased = series / series.iloc[0] * base_value
        metrics = calculate_series_metrics(rebased, annual_risk_free_rate=0.0)
        rows.append(
            {
                "series_id": f"BH_{symbol}",
                "symbol": symbol,
                "name": equity["name"],
                "currency": equity["currency"],
                "benchmark_type": "buy_and_hold",
                **metrics,
            }
        )

    return pd.DataFrame(rows)


def compute_market_benchmark(
    ticker: str,
    start: str,
    end: str | None,
    interval: str,
    max_retries: int,
    base_value: float,
    errors: PipelineErrors,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        raw = download_equity_history(ticker, start, end, interval, max_retries)
        frame = normalize_equity_frame(
            raw, {"ticker": ticker, "equity_id": ticker, "name": ticker, "currency": "USD", "exchange": None}
        )
        cleaned, _quality = clean_equity_prices([frame])
    except Exception as error:  # noqa: BLE001 - market benchmark is optional, not fatal
        LOGGER.warning("Benchmark de marché %s indisponible : %s", ticker, error)
        errors.add("market_benchmark", ticker, str(error))
        return pd.DataFrame(), pd.DataFrame()

    if cleaned.empty:
        errors.add("market_benchmark", ticker, "Aucune donnée exploitable après nettoyage.")
        return pd.DataFrame(), pd.DataFrame()

    series = cleaned.set_index("date")["adjusted_close"].sort_index()
    rebased = series / series.iloc[0] * base_value
    metrics = calculate_series_metrics(rebased, annual_risk_free_rate=0.0)
    result_row = pd.DataFrame(
        [{"series_id": f"MARKET_{ticker}", "symbol": ticker, "name": ticker, "currency": "USD", "benchmark_type": "market_index", **metrics}]
    )
    curve = pd.DataFrame({"date": rebased.index, "series_name": ticker, "series_type": "market_benchmark", "value": rebased.values})
    return result_row, curve


# ============================================================
# PORTEFEUILLE EQUAL-WEIGHT / INVERSE-VOL, DEVISE DE RÉFÉRENCE
# ============================================================

def build_reference_currency_panel(
    cleaned: pd.DataFrame,
    valid_equities: list[dict[str, Any]],
    reference_currency: str,
    start: str,
    end: str | None,
    max_retries: int,
    errors: PipelineErrors,
) -> pd.DataFrame:
    currencies = {equity["currency"] for equity in valid_equities}
    fx_rates, fx_errors = build_fx_rate_table(currencies, reference_currency, start=start, end=end, max_retries=max_retries)
    for fx_error in fx_errors:
        errors.add("fx_rate", fx_error.get("from_currency"), fx_error.get("error", ""))

    converted_columns: dict[str, pd.Series] = {}
    for equity in valid_equities:
        symbol = equity["ticker"]
        series = (
            cleaned.loc[cleaned["symbol"] == symbol]
            .set_index("date")["adjusted_close"]
            .sort_index()
            .pipe(pd.to_numeric, errors="coerce")
            .dropna()
        )
        if series.empty:
            continue
        try:
            converted_columns[symbol] = convert_price_series_to_reference(
                series, equity["currency"], reference_currency, fx_rates
            )
        except KeyError as error:
            LOGGER.warning("Ticker %s exclu du portefeuille agrégé (devise) : %s", symbol, error)
            errors.add("currency_conversion", symbol, str(error))

    return pd.DataFrame(converted_columns).sort_index()


def apply_cash_reserve(index_df: pd.DataFrame, cash_reserve: float, base_value: float) -> pd.DataFrame:
    """Scale the invested return by (1 - cash_reserve); the reserved fraction earns nothing.

    Applied as a post-processing step on the already-built index (kept outside
    build_synthetic_index, shared with commodities, to avoid touching its cash-free model)."""
    if cash_reserve <= 0 or index_df.empty:
        return index_df

    adjusted = index_df.copy()
    adjusted["daily_return"] = adjusted["daily_return"].fillna(0) * (1 - cash_reserve)
    adjusted["index_level"] = base_value * (1 + adjusted["daily_return"]).cumprod()
    running_peak = adjusted["index_level"].cummax()
    adjusted["running_peak"] = running_peak
    adjusted["drawdown"] = adjusted["index_level"] / running_peak - 1
    return adjusted


def build_equity_portfolio(
    panel_reference_currency: pd.DataFrame,
    valid_equities_by_ticker: dict[str, dict[str, Any]],
    args: argparse.Namespace,
    base_value: float = 100.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    tickers = list(panel_reference_currency.columns)
    if args.max_positions and len(tickers) > args.max_positions:
        LOGGER.warning(
            "Univers réduit à %s positions (sur %s valides) par --max-positions.",
            args.max_positions,
            len(tickers),
        )
        tickers = tickers[: args.max_positions]

    if len(tickers) < 2:
        raise ValueError("Le portefeuille agrégé nécessite au moins deux actions valides en devise de référence.")

    max_position_weight = args.max_position_weight if args.max_position_weight > 0 else None
    if max_position_weight is not None and max_position_weight * len(tickers) < 1.0:
        LOGGER.warning(
            "--max-position-weight %.3f est trop restrictif pour %s actifs (plafond total %.2f < 1) ; "
            "plafond désactivé pour cette exécution.",
            max_position_weight,
            len(tickers),
            max_position_weight * len(tickers),
        )
        max_position_weight = None

    selected_assets = {ticker: {"name": valid_equities_by_ticker[ticker]["name"]} for ticker in tickers}
    aligned, _filled_mask = align_price_panel(panel_reference_currency[tickers], selected_assets, args.max_forward_fill)

    config = IndexConfig(
        base_value=base_value,
        weighting=args.allocation,
        rebalance=args.rebalance,
        vol_lookback=args.vol_lookback,
        min_vol_observations=args.min_vol_observations,
        transaction_cost_bps=args.transaction_cost_bps,
        annual_risk_free_rate=0.0,
        max_forward_fill=args.max_forward_fill,
        price_field="close",
        max_position_weight=max_position_weight,
    )
    index_df, weights_df = build_synthetic_index(aligned, config)
    index_df = apply_cash_reserve(index_df, args.cash_reserve, base_value)
    return index_df.reset_index().rename(columns={"index": "date"}), weights_df


def build_local_currency_no_fx_portfolio(
    cleaned: pd.DataFrame,
    valid_equities: list[dict[str, Any]],
    base_value: float = 100.0,
) -> pd.DataFrame:
    """Equal-weight average of local-currency daily returns, ignoring FX entirely — the
    "sans effet de change" comparison requested for the reference-currency portfolio."""
    columns: dict[str, pd.Series] = {}
    for equity in valid_equities:
        symbol = equity["ticker"]
        series = (
            cleaned.loc[cleaned["symbol"] == symbol]
            .set_index("date")["adjusted_close"]
            .sort_index()
            .pipe(pd.to_numeric, errors="coerce")
            .dropna()
        )
        if not series.empty:
            columns[symbol] = series

    panel = pd.DataFrame(columns).sort_index().dropna(how="any")
    if panel.empty:
        return pd.DataFrame()

    returns = panel.pct_change(fill_method=None).fillna(0)
    portfolio_return = returns.mean(axis=1)
    index_level = base_value * (1 + portfolio_return).cumprod()
    running_peak = index_level.cummax()
    drawdown = index_level / running_peak - 1

    return pd.DataFrame(
        {
            "date": index_level.index,
            "index_level": index_level.values,
            "daily_return": portfolio_return.values,
            "drawdown": drawdown.values,
        }
    )


# ============================================================
# EXPORTS ET VISUELS
# ============================================================

def export_outputs(output_dir: Path, frames: dict[str, pd.DataFrame]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, frame in frames.items():
        save_csv_atomic(frame, output_dir / filename, index=False)
        LOGGER.info("Export : %s (%s lignes)", filename, len(frame))


def generate_visuals(
    output_dir: Path,
    equity_curves: pd.DataFrame,
    cleaned: pd.DataFrame,
    portfolio_daily: pd.DataFrame,
    individual_backtests: pd.DataFrame,
) -> None:
    charts_dir = output_dir / "charts"

    if not equity_curves.empty:
        for symbol in equity_curves["symbol"].dropna().unique():
            visuals.plot_equity_vs_buy_hold(equity_curves, symbol, charts_dir)
            visuals.plot_drawdown(equity_curves, symbol, charts_dir)

    if not cleaned.empty:
        price_panel = cleaned.pivot_table(index="date", columns="symbol", values="adjusted_close", aggfunc="last")
        visuals.plot_cumulative_returns_by_ticker(price_panel, charts_dir)
        returns_panel = price_panel.pct_change(fill_method=None)
        visuals.plot_correlation_heatmap(returns_panel, charts_dir)

    if not portfolio_daily.empty:
        visuals.plot_portfolio_performance(portfolio_daily, charts_dir)

    if not individual_backtests.empty and "strategy_name" in individual_backtests.columns:
        buy_hold_rows = individual_backtests.loc[individual_backtests["strategy_name"] == "buy_and_hold"].copy()
        if not buy_hold_rows.empty and {"annualized_return", "annualized_volatility", "max_drawdown"}.issubset(buy_hold_rows.columns):
            visuals.plot_risk_return_scatter(buy_hold_rows, charts_dir)
        if "sharpe_ratio" in individual_backtests.columns:
            visuals.plot_strategy_ranking(individual_backtests.dropna(subset=["sharpe_ratio"]), charts_dir, metric="sharpe_ratio")


# ============================================================
# ORCHESTRATION
# ============================================================

def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = Path.cwd() / output_dir
    log_path = configure_logging(args.log_level, output_dir / "logs")

    config = load_project_config()
    universe = load_equity_universe(config)
    selected = select_equities(universe, args.tickers)

    LOGGER.info("Univers sélectionné : %s ticker(s) sur %s configurés.", len(selected), len(universe))

    valid_equities, invalid_equities, validation_df = validate_tickers(selected, args.max_retries)

    if args.dry_run:
        print(validation_df[["ticker", "name", "currency", "valid", "rows", "error"]].to_string(index=False))
        return {"validation": validation_df}

    if not valid_equities:
        raise RuntimeError("Aucun ticker valide après validation ; pipeline interrompue.")

    errors = PipelineErrors(rows=[])
    end_date = args.end or get_default_yfinance_end_date()

    frames = []
    for equity in valid_equities:
        try:
            raw = download_equity_history(equity["ticker"], args.start, end_date, args.interval, args.max_retries)
            frames.append(normalize_equity_frame(raw, equity))
        except Exception as error:  # noqa: BLE001 - one ticker's failure must not stop the run
            LOGGER.exception("Téléchargement impossible pour %s", equity["ticker"])
            errors.add("download", equity["ticker"], str(error))
        if args.request_delay_seconds > 0:
            time.sleep(args.request_delay_seconds)

    cleaned, quality_report = clean_equity_prices(frames)
    if cleaned.empty:
        raise RuntimeError("Aucune donnée exploitable après nettoyage ; pipeline interrompue.")

    downloaded_symbols = set(cleaned["symbol"].unique())
    valid_equities = [equity for equity in valid_equities if equity["ticker"] in downloaded_symbols]
    valid_equities_by_ticker = {equity["ticker"]: equity for equity in valid_equities}

    indicator_data = attach_indicators(cleaned)

    strategy_names = list(STRATEGY_FACTORIES) if args.strategy == "all" else sorted({args.strategy, "buy_and_hold"})
    engine_config_kwargs = {
        "initial_capital": args.capital,
        "fee_rate": args.commission,
        "slippage_rate": args.slippage,
        "allow_short": args.allow_short,
        "run_at": datetime.now(UTC),
    }

    individual_backtests, trades, equity_curves = run_all_backtests(
        indicator_data, valid_equities, strategy_names, engine_config_kwargs, errors
    )

    buy_hold_benchmarks = compute_individual_buy_hold_benchmarks(cleaned, valid_equities, base_value=100.0)
    market_benchmark_row, market_benchmark_curve = compute_market_benchmark(
        args.market_benchmark, args.start, end_date, args.interval, args.max_retries, base_value=100.0, errors=errors
    )

    portfolio_daily = pd.DataFrame()
    portfolio_no_fx = pd.DataFrame()
    portfolio_summary_rows = []
    try:
        reference_panel = build_reference_currency_panel(
            cleaned, valid_equities, args.reference_currency, args.start, end_date, args.max_retries, errors
        )
        portfolio_daily, _weights = build_equity_portfolio(reference_panel, valid_equities_by_ticker, args)
        portfolio_no_fx = build_local_currency_no_fx_portfolio(cleaned, valid_equities)

        portfolio_metrics = calculate_series_metrics(
            portfolio_daily.set_index("date")["index_level"], annual_risk_free_rate=0.0
        )
        portfolio_summary_rows.append(
            {
                "series_id": "PORTFOLIO_REFERENCE_CURRENCY",
                "symbol": None,
                "name": f"Portefeuille {args.allocation} ({args.reference_currency})",
                "currency": args.reference_currency,
                "benchmark_type": "equal_weight_portfolio" if args.allocation == "equal" else "inverse_vol_portfolio",
                **portfolio_metrics,
            }
        )
        if not portfolio_no_fx.empty:
            no_fx_metrics = calculate_series_metrics(
                portfolio_no_fx.set_index("date")["index_level"], annual_risk_free_rate=0.0
            )
            portfolio_summary_rows.append(
                {
                    "series_id": "PORTFOLIO_NO_FX_EFFECT",
                    "symbol": None,
                    "name": "Portefeuille equal-weight (rendements locaux, sans effet de change)",
                    "currency": "mixed",
                    "benchmark_type": "equal_weight_portfolio_no_fx",
                    **no_fx_metrics,
                }
            )
    except Exception as error:  # noqa: BLE001 - portfolio failure must not void individual results
        LOGGER.exception("Construction du portefeuille agrégé impossible")
        errors.add("portfolio", None, str(error))

    portfolio_daily = portfolio_daily.assign(fx_adjusted=True) if not portfolio_daily.empty else portfolio_daily
    portfolio_no_fx = portfolio_no_fx.assign(fx_adjusted=False) if not portfolio_no_fx.empty else portfolio_no_fx
    portfolio_results = pd.concat([portfolio_daily, portfolio_no_fx], ignore_index=True) if (not portfolio_daily.empty or not portfolio_no_fx.empty) else pd.DataFrame()

    benchmark_results = pd.concat(
        [frame for frame in [buy_hold_benchmarks, pd.DataFrame(portfolio_summary_rows), market_benchmark_row] if not frame.empty],
        ignore_index=True,
    )

    if not market_benchmark_curve.empty:
        market_curve_renamed = market_benchmark_curve.rename(columns={"value": "equity"})
        market_curve_renamed["symbol"] = args.market_benchmark
        equity_curves = pd.concat([equity_curves, market_curve_renamed], ignore_index=True)

    export_outputs(
        output_dir,
        {
            "cleaned_prices.csv": cleaned,
            "ticker_validation.csv": validation_df,
            "data_quality_report.csv": quality_report,
            "individual_backtests.csv": individual_backtests,
            "benchmark_results.csv": benchmark_results,
            "portfolio_results.csv": portfolio_results,
            "trades.csv": trades,
            "equity_curves.csv": equity_curves,
        },
    )
    if errors.rows:
        save_csv_atomic(pd.DataFrame(errors.rows), output_dir / "logs" / "pipeline_errors.csv", index=False)

    generate_visuals(output_dir, equity_curves, cleaned, portfolio_daily, individual_backtests)

    save_json_atomic(
        {
            "start": args.start,
            "end": end_date,
            "tickers_requested": [equity["ticker"] for equity in selected],
            "tickers_valid": [equity["ticker"] for equity in valid_equities],
            "tickers_invalid": [equity["ticker"] for equity in invalid_equities],
            "strategy": args.strategy,
            "allocation": args.allocation,
            "reference_currency": args.reference_currency,
            "market_benchmark": args.market_benchmark,
        },
        output_dir / "run_config.json",
    )

    return {
        "output_dir": output_dir,
        "log_path": log_path,
        "valid_tickers": [equity["ticker"] for equity in valid_equities],
        "invalid_tickers": [equity["ticker"] for equity in invalid_equities],
        "individual_backtests": individual_backtests,
        "benchmark_results": benchmark_results,
        "portfolio_results": portfolio_results,
        "errors": errors.rows,
    }


def print_summary(result: dict[str, Any]) -> None:
    if "validation" in result:
        print("Dry-run terminé — voir le détail ci-dessus. Aucune donnée téléchargée.")
        return

    print(f"Tickers valides ({len(result['valid_tickers'])}) : {', '.join(result['valid_tickers'])}")
    if result["invalid_tickers"]:
        print(f"Tickers invalides ({len(result['invalid_tickers'])}) : {', '.join(result['invalid_tickers'])}")
    if result["errors"]:
        print(f"Erreurs consignées : {len(result['errors'])} (voir logs/pipeline_errors.csv)")
    print(f"Résultats exportés dans : {result['output_dir']}")
    print(f"Log détaillé : {result['log_path']}")


def main() -> int:
    args = parse_args()
    try:
        result = run_pipeline(args)
    except Exception as error:  # noqa: BLE001 - top-level guard, always exit cleanly with a message
        LOGGER.exception("Échec de la pipeline actions")
        print(f"Échec de la pipeline actions : {error}", file=sys.stderr)
        return 1

    print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
