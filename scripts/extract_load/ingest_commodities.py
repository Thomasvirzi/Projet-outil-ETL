from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from scripts.extract_load.config import ProjectConfig, load_project_config
except ModuleNotFoundError:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from scripts.extract_load.config import ProjectConfig, load_project_config


LOGGER = logging.getLogger(__name__)
DEFAULT_INTERVAL = "1d"
DEFAULT_YFINANCE_BATCH_SIZE = 1
DEFAULT_YFINANCE_REQUEST_DELAY_SECONDS = 2.0
YFINANCE_SOURCE = "yahoo_finance"
DATE_FORMAT = "%Y%m%d"
BOOTSTRAP_SOURCE = "local_bootstrap"
BOOTSTRAP_BASE_PRICES = {
    "CL=F": 75.0,
    "GC=F": 2050.0,
    "NG=F": 3.2,
    "HG=F": 4.4,
    "ZW=F": 610.0,
    "ZC=F": 430.0,
    "CC=F": 7200.0,
    "KC=F": 225.0,
    "BZ=F": 80.0,
    "SI=F": 29.0,
    "ZS=F": 1120.0,
    "SB=F": 19.0,
}

MARKET_DATA_SCHEMA = [
    ("date", "DATE", "REQUIRED"),
    ("commodity_id", "STRING", "REQUIRED"),
    ("commodity_name", "STRING", "NULLABLE"),
    ("label_fr", "STRING", "NULLABLE"),
    ("symbol", "STRING", "REQUIRED"),
    ("category", "STRING", "NULLABLE"),
    ("priority", "STRING", "NULLABLE"),
    ("currency", "STRING", "NULLABLE"),
    ("open", "FLOAT", "NULLABLE"),
    ("high", "FLOAT", "NULLABLE"),
    ("low", "FLOAT", "NULLABLE"),
    ("close", "FLOAT", "NULLABLE"),
    ("adjusted_close", "FLOAT", "NULLABLE"),
    ("volume", "FLOAT", "NULLABLE"),
    ("volume_filled", "FLOAT", "NULLABLE"),
    ("source", "STRING", "NULLABLE"),
    ("ingested_at", "TIMESTAMP", "NULLABLE"),
    ("open_was_missing", "INTEGER", "NULLABLE"),
    ("high_was_missing", "INTEGER", "NULLABLE"),
    ("low_was_missing", "INTEGER", "NULLABLE"),
    ("close_was_missing", "INTEGER", "NULLABLE"),
    ("adjusted_close_was_missing", "INTEGER", "NULLABLE"),
    ("volume_was_missing", "INTEGER", "NULLABLE"),
]


@dataclass(frozen=True)
class IngestionResult:
    output_path: Path
    metadata_path: Path
    errors_path: Path | None
    rows: int
    commodities: int
    bigquery_table: str | None = None
    bigquery_rows: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest Yahoo Finance OHLCV data for configured commodities."
    )
    parser.add_argument(
        "--start-date",
        help="Start date in YYYY-MM-DD format. Defaults to config/settings.yml.",
    )
    parser.add_argument(
        "--end-date",
        help=(
            "End date in YYYY-MM-DD format. Defaults to today because yfinance "
            "treats end as exclusive, so daily data is loaded up to J-1."
        ),
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help=(
            "Start from the day after the latest date already present in "
            "raw.market_data_raw. Falls back to settings.pipeline.start_date."
        ),
    )
    parser.add_argument(
        "--interval",
        default=DEFAULT_INTERVAL,
        help=f"Yahoo Finance interval. Default: {DEFAULT_INTERVAL}.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_YFINANCE_BATCH_SIZE,
        help=(
            "Number of Yahoo Finance symbols downloaded per request. "
            f"Default: {DEFAULT_YFINANCE_BATCH_SIZE} to reduce rate limiting."
        ),
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=DEFAULT_YFINANCE_REQUEST_DELAY_SECONDS,
        help=(
            "Delay between Yahoo Finance requests. "
            f"Default: {DEFAULT_YFINANCE_REQUEST_DELAY_SECONDS}."
        ),
    )
    parser.add_argument(
        "--priorities",
        nargs="*",
        choices=["A", "B", "C"],
        help="Optional commodity priorities to include.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        help="Optional Yahoo Finance symbols to include, for example GC=F CL=F.",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include commodities marked enabled: false in config/commodities.yml.",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory. Defaults to settings.paths.market_data_raw.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print the selected commodity universe without downloading data.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Do not fail if no market data row is written.",
    )
    parser.add_argument(
        "--use-local-fallback",
        action="store_true",
        help=(
            "If yfinance fails, reuse the latest local market_data_*.csv snapshot "
            "instead of overwriting the last valid state."
        ),
    )
    parser.add_argument(
        "--bootstrap-if-empty",
        action="store_true",
        help=(
            "If yfinance and local fallback both fail, generate deterministic demo "
            "market data marked as local_bootstrap."
        ),
    )
    parser.add_argument(
        "--skip-bigquery",
        action="store_true",
        help="Write local CSV files but do not load data into BigQuery.",
    )
    parser.add_argument(
        "--write-disposition",
        default="merge",
        choices=["merge", "append", "truncate"],
        help="BigQuery write mode. Default: merge on symbol/date.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level.",
    )
    return parser.parse_args()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def select_commodities(
    config: ProjectConfig,
    priorities: list[str] | None = None,
    symbols: list[str] | None = None,
    include_disabled: bool = False,
) -> list[dict[str, Any]]:
    commodities = config.commodities.get("commodities", [])

    if not include_disabled:
        commodities = [
            commodity for commodity in commodities if commodity.get("enabled", True)
        ]

    if priorities:
        allowed_priorities = set(priorities)
        commodities = [
            commodity
            for commodity in commodities
            if commodity.get("priority") in allowed_priorities
        ]

    if symbols:
        allowed_symbols = set(symbols)
        commodities = [
            commodity
            for commodity in commodities
            if commodity.get("symbol") in allowed_symbols
        ]

    if not commodities:
        raise ValueError("No commodities selected for ingestion.")

    validate_commodity_universe(commodities)
    return commodities


def validate_commodity_universe(commodities: list[dict[str, Any]]) -> None:
    required_fields = ["commodity_id", "symbol", "name", "category", "source"]

    for commodity in commodities:
        missing_fields = [
            field for field in required_fields if not commodity.get(field)
        ]
        if missing_fields:
            joined_fields = ", ".join(missing_fields)
            raise ValueError(
                f"Commodity {commodity!r} is missing required fields: {joined_fields}"
            )

    commodity_ids = [commodity["commodity_id"] for commodity in commodities]
    symbols = [commodity["symbol"] for commodity in commodities]

    if len(commodity_ids) != len(set(commodity_ids)):
        raise ValueError("commodity_id values must be unique.")

    if len(symbols) != len(set(symbols)):
        raise ValueError("symbol values must be unique.")


def build_commodities_metadata(commodities: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for commodity in commodities:
        rss_query = commodity.get("rss_query", "")
        rows.append(
            {
                "commodity_id": commodity["commodity_id"],
                "commodity_name": commodity["name"],
                "label_fr": commodity.get("label_fr"),
                "symbol": commodity["symbol"],
                "category": commodity["category"],
                "priority": commodity.get("priority"),
                "currency": commodity.get("currency"),
                "source": commodity.get("source", YFINANCE_SOURCE),
                "rss_query": rss_query,
                "rss_url": build_google_news_rss_url(rss_query)
                if rss_query
                else None,
                "enabled": commodity.get("enabled", True),
            }
        )

    return pd.DataFrame(rows)


def build_google_news_rss_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}"
        "&hl=en-US&gl=US&ceid=US:en"
    )


def symbol_seed(symbol: str) -> int:
    return sum((index + 1) * ord(character) for index, character in enumerate(symbol))


def generate_bootstrap_market_data(
    commodities: list[dict[str, Any]],
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    dates = pd.bdate_range(start=start_date, end=end_date, inclusive="left")
    if dates.empty:
        dates = pd.bdate_range(end=pd.Timestamp(end_date), periods=260)

    rows = []
    for commodity in commodities:
        symbol = commodity["symbol"]
        seed = symbol_seed(symbol)
        base_price = BOOTSTRAP_BASE_PRICES.get(symbol, 100.0 + seed % 250)
        daily_drift = ((seed % 17) - 8) / 100_000
        seasonal_amplitude = 0.015 + (seed % 7) / 1000
        volume_base = 25_000 + (seed % 500) * 100

        for day_index, market_date in enumerate(dates):
            cycle = math.sin((day_index + seed % 31) / 17)
            slow_cycle = math.cos((day_index + seed % 53) / 61)
            close = base_price * (1 + daily_drift * day_index + seasonal_amplitude * cycle + 0.01 * slow_cycle)
            close = max(close, 0.01)
            open_price = close * (1 + 0.004 * math.sin((day_index + seed) / 11))
            high = max(open_price, close) * (1 + 0.006 + (seed % 3) / 1000)
            low = min(open_price, close) * (1 - 0.006 - (seed % 5) / 1000)
            volume = volume_base + int(abs(math.sin((day_index + seed) / 9)) * volume_base * 0.4)

            rows.append(
                {
                    "date": market_date,
                    "commodity_id": commodity["commodity_id"],
                    "commodity_name": commodity["name"],
                    "label_fr": commodity.get("label_fr"),
                    "symbol": symbol,
                    "category": commodity["category"],
                    "priority": commodity.get("priority"),
                    "currency": commodity.get("currency"),
                    "open": round(open_price, 6),
                    "high": round(high, 6),
                    "low": round(low, 6),
                    "close": round(close, 6),
                    "adjusted_close": round(close, 6),
                    "volume": float(volume),
                    "volume_filled": float(volume),
                    "source": BOOTSTRAP_SOURCE,
                    "ingested_at": datetime.now(UTC).isoformat(),
                }
            )

    return pd.DataFrame(rows)


def chunk_symbols(symbols: list[str], batch_size: int) -> list[list[str]]:
    if batch_size < 1:
        raise ValueError("--batch-size must be greater than or equal to 1.")
    return [symbols[index:index + batch_size] for index in range(0, len(symbols), batch_size)]


def ensure_symbol_multiindex(frame: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    if frame.empty or isinstance(frame.columns, pd.MultiIndex):
        return frame

    if len(symbols) != 1:
        return frame

    symbol = symbols[0]
    wrapped = frame.copy()
    wrapped.columns = pd.MultiIndex.from_product([wrapped.columns, [symbol]])
    return wrapped


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def download_yfinance_data(
    symbols: list[str],
    start_date: str,
    end_date: str | None,
    interval: str,
    batch_size: int = DEFAULT_YFINANCE_BATCH_SIZE,
    request_delay_seconds: float = DEFAULT_YFINANCE_REQUEST_DELAY_SECONDS,
) -> pd.DataFrame:
    batches = chunk_symbols(symbols, batch_size)
    LOGGER.info(
        "Downloading %s symbols from yfinance in %s batch(es) of up to %s.",
        len(symbols),
        len(batches),
        batch_size,
    )
    frames = []

    for batch_index, batch_symbols in enumerate(batches, start=1):
        LOGGER.info(
            "Downloading yfinance batch %s/%s: %s",
            batch_index,
            len(batches),
            ", ".join(batch_symbols),
        )
        frame = yf.download(
            batch_symbols[0] if len(batch_symbols) == 1 else batch_symbols,
            start=start_date,
            end=end_date,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="column",
        )
        frames.append(ensure_symbol_multiindex(frame, batch_symbols))

        if batch_index < len(batches) and request_delay_seconds > 0:
            time.sleep(request_delay_seconds)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, axis=1)


def normalize_yfinance_output(
    raw_data: pd.DataFrame,
    commodities: list[dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    metadata = build_commodities_metadata(commodities)
    symbol_to_id = metadata.set_index("symbol")["commodity_id"].to_dict()
    symbols = list(symbol_to_id)

    if raw_data.empty:
        errors = pd.DataFrame(
            [
                {
                    "commodity_id": symbol_to_id[symbol],
                    "symbol": symbol,
                    "error": "No data returned by yfinance.",
                }
                for symbol in symbols
            ]
        )
        return pd.DataFrame(), errors

    normalized_frames = []

    if isinstance(raw_data.columns, pd.MultiIndex):
        ticker_level = infer_ticker_level(raw_data.columns, symbols)
        for symbol in symbols:
            try:
                if ticker_level == 0:
                    symbol_frame = raw_data[symbol].copy()
                else:
                    symbol_frame = raw_data.xs(symbol, level=ticker_level, axis=1).copy()
            except KeyError:
                continue
            normalized_frames.append(normalize_symbol_frame(symbol_frame, symbol))
    else:
        normalized_frames.append(normalize_symbol_frame(raw_data.copy(), symbols[0]))

    if not normalized_frames:
        errors = pd.DataFrame(
            [
                {
                    "commodity_id": symbol_to_id[symbol],
                    "symbol": symbol,
                    "error": "Unable to normalize yfinance output.",
                }
                for symbol in symbols
            ]
        )
        return pd.DataFrame(), errors

    prices = pd.concat(normalized_frames, ignore_index=True)
    prices["commodity_id"] = prices["symbol"].map(symbol_to_id)
    prices = prices.merge(
        metadata[
            [
                "commodity_id",
                "commodity_name",
                "label_fr",
                "category",
                "priority",
                "currency",
            ]
        ],
        on="commodity_id",
        how="left",
    )

    errors = detect_download_errors(prices, metadata)
    return prices, errors


def infer_ticker_level(columns: pd.MultiIndex, symbols: list[str]) -> int:
    symbol_set = set(symbols)
    for level in range(columns.nlevels):
        values = set(columns.get_level_values(level).astype(str))
        if symbol_set.intersection(values):
            return level
    return columns.nlevels - 1


def normalize_symbol_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    frame = frame.reset_index()
    frame.columns = [normalize_column_name(column) for column in frame.columns]

    if "datetime" in frame.columns and "date" not in frame.columns:
        frame = frame.rename(columns={"datetime": "date"})

    if "index" in frame.columns and "date" not in frame.columns:
        frame = frame.rename(columns={"index": "date"})

    if "adj_close" in frame.columns:
        frame = frame.rename(columns={"adj_close": "adjusted_close"})

    frame["symbol"] = symbol
    return frame


def normalize_column_name(column: Any) -> str:
    return str(column).strip().lower().replace(" ", "_")


def detect_download_errors(prices: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    errors = []

    for row in metadata.itertuples(index=False):
        symbol_prices = prices[prices["symbol"] == row.symbol]
        if symbol_prices.empty:
            errors.append(
                {
                    "commodity_id": row.commodity_id,
                    "symbol": row.symbol,
                    "error": "No row returned after normalization.",
                }
            )
            continue

        if "close" not in symbol_prices or symbol_prices["close"].isna().all():
            errors.append(
                {
                    "commodity_id": row.commodity_id,
                    "symbol": row.symbol,
                    "error": "Close column is fully empty.",
                }
            )

    return pd.DataFrame(errors)


def clean_market_data(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return prices

    cleaned = prices.copy()
    cleaned["date"] = pd.to_datetime(cleaned["date"], utc=True, errors="coerce")
    cleaned["date"] = cleaned["date"].dt.tz_convert(None).dt.normalize()

    numeric_columns = [
        column
        for column in ["open", "high", "low", "close", "adjusted_close", "volume"]
        if column in cleaned.columns
    ]
    cleaned[numeric_columns] = cleaned[numeric_columns].apply(
        pd.to_numeric, errors="coerce"
    )
    cleaned[numeric_columns] = cleaned[numeric_columns].replace(
        [float("inf"), float("-inf")], pd.NA
    )

    cleaned = cleaned.dropna(subset=["date", "commodity_id", "symbol"])
    cleaned = cleaned.drop_duplicates()

    if numeric_columns:
        cleaned["_completeness"] = cleaned[numeric_columns].notna().sum(axis=1)
        cleaned = (
            cleaned.sort_values(
                ["symbol", "date", "_completeness"],
                ascending=[True, True, False],
            )
            .drop_duplicates(subset=["symbol", "date"], keep="first")
            .drop(columns="_completeness")
        )

    for column in numeric_columns:
        cleaned[f"{column}_was_missing"] = cleaned[column].isna().astype("int8")

    if {"adjusted_close", "close"}.issubset(cleaned.columns):
        cleaned["adjusted_close"] = cleaned["adjusted_close"].fillna(cleaned["close"])

    if "volume" in cleaned.columns:
        cleaned["volume_filled"] = cleaned["volume"].fillna(0)

    if "close" in cleaned.columns:
        cleaned = cleaned.dropna(subset=["close"])

    required_ohlc = {"open", "high", "low", "close"}
    if required_ohlc.issubset(cleaned.columns):
        ohlc_columns = ["open", "high", "low", "close"]
        cleaned["high"] = cleaned[ohlc_columns].max(axis=1)
        cleaned["low"] = cleaned[ohlc_columns].min(axis=1)

        price_columns = ["open", "high", "low", "close"]
        invalid_price_mask = (
            cleaned[price_columns].le(0).any(axis=1)
            & cleaned["symbol"].ne("CL=F")
        )
        cleaned = cleaned.loc[~invalid_price_mask].copy()

    if "source" not in cleaned.columns:
        cleaned["source"] = YFINANCE_SOURCE
    else:
        cleaned["source"] = cleaned["source"].fillna(YFINANCE_SOURCE)
    cleaned["ingested_at"] = datetime.now(UTC).isoformat()

    output_columns = [
        "date",
        "commodity_id",
        "commodity_name",
        "label_fr",
        "symbol",
        "category",
        "priority",
        "currency",
        "open",
        "high",
        "low",
        "close",
        "adjusted_close",
        "volume",
        "volume_filled",
        "source",
        "ingested_at",
    ]
    missing_flag_columns = [
        column for column in cleaned.columns if column.endswith("_was_missing")
    ]
    ordered_columns = [
        column for column in output_columns + missing_flag_columns if column in cleaned
    ]

    return (
        cleaned[ordered_columns]
        .sort_values(["symbol", "date"])
        .reset_index(drop=True)
    )


def write_outputs(
    prices: pd.DataFrame,
    metadata: pd.DataFrame,
    errors: pd.DataFrame,
    output_dir: Path,
    run_date: datetime | None = None,
) -> IngestionResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_date = run_date or datetime.now(UTC)
    suffix = run_date.strftime(DATE_FORMAT)

    output_path = output_dir / f"market_data_{suffix}.csv"
    metadata_path = output_dir / f"commodities_reference_{suffix}.csv"
    errors_path = (
        output_dir / f"market_data_errors_{suffix}.csv"
        if not errors.empty
        else None
    )

    prices.to_csv(output_path, index=False, encoding="utf-8", date_format="%Y-%m-%d")
    metadata.to_csv(metadata_path, index=False, encoding="utf-8")

    if errors_path:
        errors.to_csv(errors_path, index=False, encoding="utf-8")

    return IngestionResult(
        output_path=output_path,
        metadata_path=metadata_path,
        errors_path=errors_path,
        rows=len(prices),
        commodities=prices["symbol"].nunique() if "symbol" in prices else 0,
    )


def is_valid_market_data_snapshot(path: Path) -> bool:
    try:
        return len(pd.read_csv(path, nrows=1)) > 0
    except Exception:
        return False


def find_latest_market_data_snapshot(output_dir: Path) -> Path | None:
    if not output_dir.exists():
        return None

    candidates = sorted(
        output_dir.glob("market_data_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].csv")
    )
    valid_candidates = [candidate for candidate in candidates if is_valid_market_data_snapshot(candidate)]
    return valid_candidates[-1] if valid_candidates else None


def load_latest_market_data_snapshot(output_dir: Path) -> pd.DataFrame:
    latest_snapshot = find_latest_market_data_snapshot(output_dir)
    if latest_snapshot is None:
        raise FileNotFoundError(
            f"No local market_data_YYYYMMDD.csv snapshot found in {output_dir}."
        )

    LOGGER.warning("Using local fallback market data snapshot: %s", latest_snapshot)
    return pd.read_csv(latest_snapshot)


def get_market_data_columns() -> list[str]:
    return [field[0] for field in MARKET_DATA_SCHEMA]


def import_bigquery_module() -> Any:
    try:
        from google.cloud import bigquery
    except ImportError as error:
        raise RuntimeError(
            "google-cloud-bigquery is required to load data into BigQuery. "
            "Install dependencies with `make install`."
        ) from error
    return bigquery


def build_market_data_schema() -> list[Any]:
    bigquery = import_bigquery_module()
    return [
        bigquery.SchemaField(name, field_type, mode=mode)
        for name, field_type, mode in MARKET_DATA_SCHEMA
    ]


def get_market_data_table_id(config: ProjectConfig) -> str:
    project_id = config.environment.google_cloud_project
    if not project_id:
        raise ValueError(
            "GOOGLE_CLOUD_PROJECT is required to load market data into BigQuery."
        )

    dataset = config.settings["bigquery"]["raw_dataset"]
    table = config.settings["bigquery"]["tables"]["market_data_raw"]
    return f"{project_id}.{dataset}.{table}"


def get_default_yfinance_end_date(now: datetime | None = None) -> str:
    reference = now or datetime.now(UTC)
    return reference.date().isoformat()


def next_daily_start_date(last_loaded_date: Any, fallback_start_date: str) -> str:
    if last_loaded_date is None or pd.isna(last_loaded_date):
        return fallback_start_date

    next_date = pd.Timestamp(last_loaded_date).date() + timedelta(days=1)
    return next_date.isoformat()


def get_latest_market_date(client: Any, table_id: str, location: str) -> Any:
    query = f"SELECT MAX(date) AS max_date FROM `{table_id}`"
    rows = list(client.query(query, location=location).result())
    if not rows:
        return None
    return getattr(rows[0], "max_date", None)


def resolve_market_date_window(
    args: argparse.Namespace,
    config: ProjectConfig,
    client: Any | None = None,
) -> tuple[str, str]:
    start_date = args.start_date or config.settings["pipeline"]["start_date"]
    end_date = args.end_date or get_default_yfinance_end_date()

    if not getattr(args, "incremental", False):
        return start_date, end_date

    bigquery = import_bigquery_module()
    location = config.settings["bigquery"].get("location", "EU")
    table_id = get_market_data_table_id(config)
    client = client or bigquery.Client(
        project=config.environment.google_cloud_project,
        location=location,
    )
    latest_date = get_latest_market_date(client, table_id, location)
    return next_daily_start_date(latest_date, start_date), end_date


def prepare_bigquery_dataframe(prices: pd.DataFrame) -> pd.DataFrame:
    schema_columns = get_market_data_columns()
    dataframe = prices.copy()

    if "date" in dataframe.columns:
        dataframe["date"] = pd.to_datetime(dataframe["date"]).dt.date

    if "ingested_at" in dataframe.columns:
        dataframe["ingested_at"] = pd.to_datetime(dataframe["ingested_at"], utc=True)

    for column in schema_columns:
        if column not in dataframe.columns:
            dataframe[column] = None

    return dataframe[schema_columns]


def ensure_market_data_table(
    client: Any,
    table_id: str,
    location: str,
) -> Any:
    bigquery = import_bigquery_module()
    schema = build_market_data_schema()
    table = bigquery.Table(table_id, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="date",
    )
    table.clustering_fields = ["symbol"]

    try:
        return client.get_table(table_id)
    except Exception:
        LOGGER.info("Creating BigQuery table %s.", table_id)
        return client.create_table(table)


def load_market_data_to_bigquery(
    prices: pd.DataFrame,
    config: ProjectConfig,
    write_disposition: str = "merge",
    client: Any | None = None,
) -> tuple[str, int]:
    bigquery = import_bigquery_module()
    if prices.empty:
        raise ValueError("Cannot load empty market data dataframe into BigQuery.")

    table_id = get_market_data_table_id(config)
    project_id = config.environment.google_cloud_project
    location = config.settings["bigquery"].get("location", "EU")
    client = client or bigquery.Client(project=project_id, location=location)
    dataframe = prepare_bigquery_dataframe(prices)
    schema = build_market_data_schema()

    ensure_market_data_table(client, table_id, location)

    if write_disposition == "append":
        job_config = bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )
        load_job = client.load_table_from_dataframe(
            dataframe,
            table_id,
            job_config=job_config,
            location=location,
        )
        load_job.result()
        return table_id, len(dataframe)

    if write_disposition == "truncate":
        job_config = bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        load_job = client.load_table_from_dataframe(
            dataframe,
            table_id,
            job_config=job_config,
            location=location,
        )
        load_job.result()
        return table_id, len(dataframe)

    return merge_market_data_to_bigquery(
        client=client,
        dataframe=dataframe,
        table_id=table_id,
        schema=schema,
        location=location,
    )


def merge_market_data_to_bigquery(
    client: Any,
    dataframe: pd.DataFrame,
    table_id: str,
    schema: list[Any],
    location: str,
) -> tuple[str, int]:
    bigquery = import_bigquery_module()
    project = table_id.split(".")[0]
    dataset = table_id.split(".")[1]
    table = table_id.split(".")[2]
    temp_table_id = f"{project}.{dataset}._tmp_{table}_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    load_job = client.load_table_from_dataframe(
        dataframe,
        temp_table_id,
        job_config=job_config,
        location=location,
    )
    load_job.result()

    columns = [field.name for field in schema]
    update_columns = [column for column in columns if column not in {"symbol", "date"}]
    update_clause = ",\n        ".join(
        f"target.{column} = source.{column}" for column in update_columns
    )
    insert_columns = ", ".join(columns)
    insert_values = ", ".join(f"source.{column}" for column in columns)

    merge_sql = f"""
    MERGE `{table_id}` AS target
    USING `{temp_table_id}` AS source
    ON target.symbol = source.symbol
       AND target.date = source.date
    WHEN MATCHED THEN
      UPDATE SET
        {update_clause}
    WHEN NOT MATCHED THEN
      INSERT ({insert_columns})
      VALUES ({insert_values})
    """

    try:
        query_job = client.query(merge_sql, location=location)
        query_job.result()
    finally:
        client.delete_table(temp_table_id, not_found_ok=True)

    return table_id, len(dataframe)


def resolve_output_dir(config: ProjectConfig, output_dir: str | None) -> Path:
    configured_path = output_dir or config.settings["paths"]["market_data_raw"]
    path = Path(configured_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def ingest_commodities(args: argparse.Namespace) -> IngestionResult | None:
    config = load_project_config()
    start_date, end_date = resolve_market_date_window(args, config)
    output_dir = resolve_output_dir(config, args.output_dir)
    configured_commodities = config.commodities.get("commodities", [])

    commodities = select_commodities(
        config=config,
        priorities=args.priorities,
        symbols=args.symbols,
        include_disabled=args.include_disabled,
    )

    metadata = build_commodities_metadata(commodities)
    enabled_count = sum(
        commodity.get("enabled", True) for commodity in configured_commodities
    )
    LOGGER.info(
        "Selected %s commodity symbol(s) from %s configured (%s enabled, %s disabled).",
        len(commodities),
        len(configured_commodities),
        enabled_count,
        len(configured_commodities) - enabled_count,
    )

    if args.dry_run:
        print(metadata[["commodity_id", "symbol", "priority", "enabled"]].to_string(index=False))
        return None

    symbols = metadata["symbol"].tolist()
    try:
        raw_data = download_yfinance_data(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            interval=args.interval,
            batch_size=args.batch_size,
            request_delay_seconds=args.request_delay_seconds,
        )
        prices, errors = normalize_yfinance_output(raw_data, commodities)
    except Exception as error:
        if not args.use_local_fallback:
            raise

        LOGGER.warning(
            "yfinance download failed; preserving the last valid local snapshot.",
            exc_info=error,
        )
        prices = load_latest_market_data_snapshot(output_dir)
        errors = pd.DataFrame(
            [
                {
                    "commodity_id": None,
                    "symbol": None,
                    "error": f"Used local fallback after source failure: {error}",
                }
            ]
        )
    clean_prices = clean_market_data(prices)
    if clean_prices.empty and args.use_local_fallback:
        LOGGER.warning(
            "yfinance returned no clean market rows; trying the latest valid local snapshot."
        )
        try:
            fallback_prices = load_latest_market_data_snapshot(output_dir)
            fallback_errors = pd.DataFrame(
                [
                    {
                        "commodity_id": None,
                        "symbol": None,
                        "error": "Used local fallback after yfinance returned no clean market rows.",
                    }
                ]
            )
            clean_prices = clean_market_data(fallback_prices)
            errors = pd.concat([errors, fallback_errors], ignore_index=True)
        except FileNotFoundError:
            if not args.bootstrap_if_empty:
                raise

            LOGGER.warning(
                "No valid local snapshot found; generating deterministic bootstrap market data."
            )
            bootstrap_prices = generate_bootstrap_market_data(
                commodities=commodities,
                start_date=start_date,
                end_date=end_date,
            )
            bootstrap_errors = pd.DataFrame(
                [
                    {
                        "commodity_id": None,
                        "symbol": None,
                        "error": (
                            "Used deterministic local_bootstrap market data because "
                            "yfinance was rate-limited and no valid local snapshot existed."
                        ),
                    }
                ]
            )
            clean_prices = clean_market_data(bootstrap_prices)
            errors = pd.concat([errors, bootstrap_errors], ignore_index=True)

    result = write_outputs(clean_prices, metadata, errors, output_dir)

    LOGGER.info("Market data rows written: %s", result.rows)
    LOGGER.info("Market data CSV: %s", result.output_path)
    LOGGER.info("Commodity reference CSV: %s", result.metadata_path)
    if result.errors_path:
        LOGGER.warning("Download errors CSV: %s", result.errors_path)

    if result.rows == 0 and not args.allow_empty:
        raise RuntimeError(
            "No market data rows were written. Check yfinance availability "
            "and the generated errors CSV."
        )

    if result.rows > 0 and not args.skip_bigquery:
        table_id, loaded_rows = load_market_data_to_bigquery(
            prices=clean_prices,
            config=config,
            write_disposition=args.write_disposition,
        )
        result = IngestionResult(
            output_path=result.output_path,
            metadata_path=result.metadata_path,
            errors_path=result.errors_path,
            rows=result.rows,
            commodities=result.commodities,
            bigquery_table=table_id,
            bigquery_rows=loaded_rows,
        )
        LOGGER.info("BigQuery table loaded: %s", table_id)
        LOGGER.info("BigQuery rows processed: %s", loaded_rows)

    return result


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)
    ingest_commodities(args)


if __name__ == "__main__":
    main()
