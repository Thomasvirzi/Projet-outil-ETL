from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from scripts.extract_load.commodity_benchmark_index import (
        IndexConfig,
        align_price_panel,
        build_buy_and_hold_indices,
        build_master_dataset,
        build_synthetic_index,
    )
    from scripts.extract_load.config import ProjectConfig, load_project_config
except ModuleNotFoundError:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from scripts.extract_load.commodity_benchmark_index import (
        IndexConfig,
        align_price_panel,
        build_buy_and_hold_indices,
        build_master_dataset,
        build_synthetic_index,
    )
    from scripts.extract_load.config import ProjectConfig, load_project_config


LOGGER = logging.getLogger(__name__)
YFINANCE_SOURCE = "yahoo_finance"
DATE_FORMAT = "%Y%m%d"

BENCHMARK_SCHEMA = [
    ("date", "DATE", "REQUIRED"),
    ("benchmark_id", "STRING", "REQUIRED"),
    ("benchmark_type", "STRING", "REQUIRED"),
    ("benchmark_name", "STRING", "NULLABLE"),
    ("component_id", "STRING", "NULLABLE"),
    ("component_symbol", "STRING", "NULLABLE"),
    ("component_name", "STRING", "NULLABLE"),
    ("category", "STRING", "NULLABLE"),
    ("priority", "STRING", "NULLABLE"),
    ("close_price", "FLOAT", "NULLABLE"),
    ("benchmark_level", "FLOAT", "NULLABLE"),
    ("daily_return", "FLOAT", "NULLABLE"),
    ("drawdown", "FLOAT", "NULLABLE"),
    ("actual_weight", "FLOAT", "NULLABLE"),
    ("target_weight", "FLOAT", "NULLABLE"),
    ("rebalance_executed", "BOOLEAN", "NULLABLE"),
    ("source", "STRING", "NULLABLE"),
    ("methodology", "STRING", "NULLABLE"),
    ("ingested_at", "TIMESTAMP", "NULLABLE"),
]


@dataclass(frozen=True)
class BenchmarkIngestionResult:
    output_path: Path
    metadata_path: Path
    rows: int
    benchmarks: int
    bigquery_table: str | None = None
    bigquery_rows: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and ingest benchmark data into raw.benchmarks_raw."
    )
    parser.add_argument(
        "--input-market-csv",
        type=Path,
        help="Optional local market_data_YYYYMMDD.csv produced by ingest_commodities.py.",
    )
    parser.add_argument(
        "--use-market-data-fallback",
        action="store_true",
        help=(
            "If Yahoo Finance benchmark downloads fail, reuse the latest valid "
            "market_data_YYYYMMDD.csv produced by ingest_commodities.py."
        ),
    )
    parser.add_argument(
        "--prefer-market-data-fallback",
        action="store_true",
        help=(
            "Use the latest valid market_data_YYYYMMDD.csv directly instead of "
            "trying Yahoo Finance first."
        ),
    )
    parser.add_argument(
        "--start-date",
        help="Start date in YYYY-MM-DD format. Defaults to config/settings.yml.",
    )
    parser.add_argument("--end-date", help="Optional end date in YYYY-MM-DD format.")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help=(
            "Start from the day after the latest date already present in "
            "raw.benchmarks_raw. Falls back to settings.pipeline.start_date."
        ),
    )
    parser.add_argument(
        "--priorities",
        nargs="*",
        choices=["A", "B", "C"],
        help="Commodity priorities to include. Defaults to enabled A/B commodities.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        help="Optional commodity symbols to include, for example GC=F CL=F.",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include commodities marked enabled: false.",
    )
    parser.add_argument(
        "--skip-global-external",
        action="store_true",
        help="Do not download the external global benchmark.",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory. Defaults to settings.paths.benchmarks_raw.",
    )
    parser.add_argument(
        "--skip-bigquery",
        action="store_true",
        help="Write local CSV files but do not load data into BigQuery.",
    )
    parser.add_argument(
        "--min-coverage-ratio",
        type=float,
        default=0.80,
        help="Minimum non-null price coverage required per benchmark component.",
    )
    parser.add_argument(
        "--write-disposition",
        default="merge",
        choices=["merge", "append", "truncate"],
        help="BigQuery write mode. Default: merge on benchmark_id/date/component_id.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print selected benchmark universe without downloading or loading data.",
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


def select_benchmark_commodities(
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

    selected_priorities = set(priorities or ["A", "B"])
    commodities = [
        commodity
        for commodity in commodities
        if commodity.get("priority") in selected_priorities
    ]

    if symbols:
        selected_symbols = set(symbols)
        commodities = [
            commodity
            for commodity in commodities
            if commodity.get("symbol") in selected_symbols
        ]

    if len(commodities) < 2:
        raise ValueError("At least two commodities are required to build benchmarks.")

    return commodities


def build_selected_assets(
    commodities: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    return {
        commodity["commodity_id"]: {
            "name": commodity["name"],
            "ticker": commodity["symbol"],
            "category": commodity["category"],
            "priority": commodity.get("priority", ""),
        }
        for commodity in commodities
    }


def build_index_config(config: ProjectConfig) -> IndexConfig:
    synthetic_config = config.benchmarks["benchmarks"]["synthetic_index"]
    return IndexConfig(
        base_value=float(synthetic_config.get("base_value", 100)),
        weighting=synthetic_config.get("weighting", "equal"),
        rebalance=synthetic_config.get("rebalance", "monthly"),
        vol_lookback=int(synthetic_config.get("vol_lookback", 60)),
        min_vol_observations=int(synthetic_config.get("min_vol_observations", 20)),
        transaction_cost_bps=float(synthetic_config.get("transaction_cost_bps", 0)),
        annual_risk_free_rate=float(synthetic_config.get("annual_risk_free_rate", 0)),
        max_forward_fill=int(synthetic_config.get("max_forward_fill", 2)),
        price_field=synthetic_config.get("price_field", "close"),
    )


def get_default_yfinance_end_date(now: datetime | None = None) -> str:
    reference = now or datetime.now(UTC)
    return reference.date().isoformat()


def next_daily_start_date(last_loaded_date: Any, fallback_start_date: str) -> str:
    if last_loaded_date is None or pd.isna(last_loaded_date):
        return fallback_start_date

    next_date = pd.Timestamp(last_loaded_date).date() + timedelta(days=1)
    return next_date.isoformat()


def load_price_panel_from_market_csv(
    csv_path: Path,
    selected_assets: dict[str, dict[str, str]],
    price_field: str,
) -> pd.DataFrame:
    if not csv_path.exists():
        raise FileNotFoundError(f"Market data CSV not found: {csv_path}")

    data = pd.read_csv(csv_path)
    required_columns = {"date", "commodity_id", price_field}
    missing_columns = required_columns.difference(data.columns)
    if missing_columns:
        raise ValueError(f"Missing columns in market CSV: {sorted(missing_columns)}")

    data["date"] = pd.to_datetime(data["date"], utc=True, errors="coerce")
    data[price_field] = pd.to_numeric(data[price_field], errors="coerce")
    data = data.dropna(subset=["date", "commodity_id", price_field])
    data = data[data["commodity_id"].isin(selected_assets)]

    panel = data.pivot_table(
        index="date",
        columns="commodity_id",
        values=price_field,
        aggfunc="last",
    ).sort_index()
    if "source" in data.columns and not data["source"].dropna().empty:
        panel.attrs["source"] = str(data["source"].dropna().iloc[-1])

    missing_assets = sorted(set(selected_assets).difference(panel.columns))
    if missing_assets:
        raise ValueError("Assets missing from market CSV: " + ", ".join(missing_assets))

    return panel[list(selected_assets)]


def is_valid_market_data_snapshot(path: Path) -> bool:
    try:
        data = pd.read_csv(path, nrows=1)
        return not data.empty
    except Exception:
        return False


def find_latest_market_data_snapshot(market_data_dir: Path) -> Path | None:
    if not market_data_dir.exists():
        return None

    candidates = sorted(
        market_data_dir.glob("market_data_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].csv")
    )
    valid_candidates = [candidate for candidate in candidates if is_valid_market_data_snapshot(candidate)]
    return valid_candidates[-1] if valid_candidates else None


def resolve_market_data_fallback_path(config: ProjectConfig) -> Path:
    configured_path = Path(config.settings["paths"]["market_data_raw"])
    market_data_dir = configured_path if configured_path.is_absolute() else Path.cwd() / configured_path
    latest_snapshot = find_latest_market_data_snapshot(market_data_dir)
    if latest_snapshot is None:
        raise FileNotFoundError(
            f"No valid market_data_YYYYMMDD.csv snapshot found in {market_data_dir}."
        )
    return latest_snapshot


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)
def download_symbol_prices(
    symbol: str,
    start_date: str,
    end_date: str | None,
    price_field: str = "close",
) -> pd.Series:
    data = yf.download(
        symbol,
        start=start_date,
        end=end_date,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if data is None or data.empty:
        raise ValueError(f"No data returned for {symbol}.")

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    column = "Adj Close" if price_field == "adjusted_close" else "Close"
    if column not in data.columns:
        column = "Close"

    series = pd.to_numeric(data[column], errors="coerce")
    series.index = pd.to_datetime(series.index, utc=True, errors="coerce")
    series = series[~series.index.isna()]
    return series.dropna()


def download_price_panel(
    selected_assets: dict[str, dict[str, str]],
    start_date: str,
    end_date: str | None,
    price_field: str,
) -> pd.DataFrame:
    series_by_asset = {}
    for asset_id, metadata in selected_assets.items():
        symbol = metadata["ticker"]
        LOGGER.info("Downloading benchmark component %s (%s).", asset_id, symbol)
        series_by_asset[asset_id] = download_symbol_prices(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            price_field=price_field,
        )

    panel = pd.concat(series_by_asset, axis=1).sort_index()
    panel.index.name = "date"
    return panel


def validate_benchmark_coverage(
    aligned_prices: pd.DataFrame,
    selected_assets: dict[str, dict[str, str]],
    min_coverage_ratio: float,
) -> None:
    if not 0 < min_coverage_ratio <= 1:
        raise ValueError("min_coverage_ratio must be between 0 and 1.")

    if aligned_prices.empty:
        raise ValueError("Benchmark price panel is empty.")

    missing_assets = sorted(set(selected_assets).difference(aligned_prices.columns))
    if missing_assets:
        raise ValueError(
            "Benchmark price panel is missing assets: " + ", ".join(missing_assets)
        )

    coverage = aligned_prices[list(selected_assets)].notna().mean()
    insufficient_assets = coverage[coverage < min_coverage_ratio]
    if insufficient_assets.empty:
        return

    details = ", ".join(
        f"{asset_id}={ratio:.1%}" for asset_id, ratio in insufficient_assets.items()
    )
    raise ValueError(
        "Insufficient benchmark price coverage "
        f"(minimum {min_coverage_ratio:.0%}): {details}"
    )


def build_benchmark_dataset(
    aligned_prices: pd.DataFrame,
    selected_assets: dict[str, dict[str, str]],
    config: ProjectConfig,
    source: str = YFINANCE_SOURCE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    benchmark_config = config.benchmarks["benchmarks"]
    index_config = build_index_config(config)
    aligned_prices = aligned_prices.copy()
    aligned_prices.index.name = "date"

    synthetic_df, weights_df = build_synthetic_index(aligned_prices, index_config)
    buy_hold_df = build_buy_and_hold_indices(
        prices=aligned_prices,
        start_date=synthetic_df.index[0],
        base_value=index_config.base_value,
    )
    master_df = build_master_dataset(
        aligned_prices=aligned_prices,
        buy_hold_df=buy_hold_df,
        index_df=synthetic_df,
        weights_df=weights_df,
        selected_assets=selected_assets,
    )

    ingested_at = datetime.now(UTC).isoformat()
    rows = []

    buy_hold_config = benchmark_config["buy_and_hold"]
    for row in master_df.itertuples(index=False):
        rows.append(
            {
                "date": row.date,
                "benchmark_id": f"{buy_hold_config['benchmark_id_prefix']}_{row.commodity_id.lower()}",
                "benchmark_type": buy_hold_config["benchmark_type"],
                "benchmark_name": f"Buy & Hold {row.commodity_name}",
                "component_id": row.commodity_id,
                "component_symbol": row.ticker,
                "component_name": row.commodity_name,
                "category": row.category,
                "priority": row.priority,
                "close_price": row.close_price,
                "benchmark_level": row.buy_hold_index,
                "daily_return": row.buy_hold_daily_return,
                "drawdown": None,
                "actual_weight": None,
                "target_weight": None,
                "rebalance_executed": None,
                "source": source,
                "methodology": "Passive price index rebased to configured base value.",
                "ingested_at": ingested_at,
            }
        )

    synthetic_config = benchmark_config["synthetic_index"]
    for row in master_df.itertuples(index=False):
        rows.append(
            {
                "date": row.date,
                "benchmark_id": synthetic_config["benchmark_id"],
                "benchmark_type": synthetic_config["benchmark_type"],
                "benchmark_name": synthetic_config["name"],
                "component_id": row.commodity_id,
                "component_symbol": row.ticker,
                "component_name": row.commodity_name,
                "category": row.category,
                "priority": row.priority,
                "close_price": row.close_price,
                "benchmark_level": row.synthetic_index_level,
                "daily_return": row.synthetic_index_return,
                "drawdown": row.synthetic_index_drawdown,
                "actual_weight": row.actual_weight,
                "target_weight": row.target_weight,
                "rebalance_executed": row.rebalance_executed,
                "source": source,
                "methodology": (
                    "Research synthetic commodity index based on continuous Yahoo "
                    "Finance futures proxies; not a fully investable futures index."
                ),
                "ingested_at": ingested_at,
            }
        )

    metadata = pd.DataFrame(
        [
            {
                "benchmark_id": benchmark_config["synthetic_index"]["benchmark_id"],
                "benchmark_type": benchmark_config["synthetic_index"]["benchmark_type"],
                "benchmark_name": benchmark_config["synthetic_index"]["name"],
                "methodology": benchmark_config["synthetic_index"]["description"],
            },
            {
                "benchmark_id": "buy_hold_*",
                "benchmark_type": benchmark_config["buy_and_hold"]["benchmark_type"],
                "benchmark_name": "Buy & Hold per commodity",
                "methodology": benchmark_config["buy_and_hold"]["description"],
            },
        ]
    )

    return pd.DataFrame(rows), metadata


def append_global_external_benchmark(
    benchmarks: pd.DataFrame,
    metadata: pd.DataFrame,
    config: ProjectConfig,
    start_date: str,
    end_date: str | None,
    skip_global_external: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    global_config = config.benchmarks["benchmarks"].get("global_external", {})
    if skip_global_external or not global_config.get("enabled", False):
        return benchmarks, metadata

    symbol = global_config["symbol"]
    LOGGER.info("Downloading external global benchmark %s.", symbol)
    series = download_symbol_prices(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        price_field="close",
    )
    if series.empty:
        return benchmarks, metadata

    base_value = float(config.benchmarks["benchmarks"]["buy_and_hold"].get("base_value", 100))
    level = series.divide(series.iloc[0]).multiply(base_value)
    rows = pd.DataFrame(
        {
            "date": series.index,
            "benchmark_id": global_config["benchmark_id"],
            "benchmark_type": global_config["benchmark_type"],
            "benchmark_name": global_config["name"],
            "component_id": "GLOBAL",
            "component_symbol": symbol,
            "component_name": global_config["name"],
            "category": global_config["category"],
            "priority": None,
            "close_price": series.values,
            "benchmark_level": level.values,
            "daily_return": level.pct_change(fill_method=None).values,
            "drawdown": level.divide(level.cummax()).subtract(1).values,
            "actual_weight": None,
            "target_weight": None,
            "rebalance_executed": None,
            "source": global_config.get("source", YFINANCE_SOURCE),
            "methodology": "External diversified commodity market proxy rebased to base value.",
            "ingested_at": datetime.now(UTC).isoformat(),
        }
    )
    metadata = pd.concat(
        [
            metadata,
            pd.DataFrame(
                [
                    {
                        "benchmark_id": global_config["benchmark_id"],
                        "benchmark_type": global_config["benchmark_type"],
                        "benchmark_name": global_config["name"],
                        "methodology": "External diversified commodity market proxy.",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    return pd.concat([benchmarks, rows], ignore_index=True), metadata


def clean_benchmark_dataset(dataframe: pd.DataFrame) -> pd.DataFrame:
    cleaned = dataframe.copy()
    cleaned["date"] = pd.to_datetime(cleaned["date"], utc=True, errors="coerce")
    cleaned["date"] = cleaned["date"].dt.tz_convert(None).dt.date
    cleaned["ingested_at"] = pd.to_datetime(cleaned["ingested_at"], utc=True)
    cleaned = cleaned.dropna(subset=["date", "benchmark_id", "benchmark_type"])
    cleaned = cleaned.drop_duplicates(
        subset=["date", "benchmark_id", "component_id"],
        keep="last",
    )
    return cleaned[get_benchmark_columns()].sort_values(
        ["benchmark_id", "component_id", "date"],
        na_position="last",
    )


def get_benchmark_columns() -> list[str]:
    return [field[0] for field in BENCHMARK_SCHEMA]


def import_bigquery_module() -> Any:
    try:
        from google.cloud import bigquery
    except ImportError as error:
        raise RuntimeError(
            "google-cloud-bigquery is required to load data into BigQuery. "
            "Install dependencies with `make install`."
        ) from error
    return bigquery


def build_benchmark_schema() -> list[Any]:
    bigquery = import_bigquery_module()
    return [
        bigquery.SchemaField(name, field_type, mode=mode)
        for name, field_type, mode in BENCHMARK_SCHEMA
    ]


def get_benchmarks_table_id(config: ProjectConfig) -> str:
    project_id = config.environment.google_cloud_project
    if not project_id:
        raise ValueError("GOOGLE_CLOUD_PROJECT is required to load benchmarks.")

    dataset = config.settings["bigquery"]["raw_dataset"]
    table = config.settings["bigquery"]["tables"]["benchmarks_raw"]
    return f"{project_id}.{dataset}.{table}"


def get_latest_benchmark_date(client: Any, table_id: str, location: str) -> Any:
    query = f"SELECT MAX(date) AS max_date FROM `{table_id}`"
    rows = list(client.query(query, location=location).result())
    if not rows:
        return None
    return getattr(rows[0], "max_date", None)


def resolve_benchmark_date_window(
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
    table_id = get_benchmarks_table_id(config)
    client = client or bigquery.Client(
        project=config.environment.google_cloud_project,
        location=location,
    )
    latest_date = get_latest_benchmark_date(client, table_id, location)
    return next_daily_start_date(latest_date, start_date), end_date


def ensure_benchmarks_table(client: Any, table_id: str) -> Any:
    bigquery = import_bigquery_module()
    table = bigquery.Table(table_id, schema=build_benchmark_schema())
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="date",
    )
    table.clustering_fields = ["benchmark_id", "benchmark_type"]

    try:
        return client.get_table(table_id)
    except Exception:
        LOGGER.info("Creating BigQuery table %s.", table_id)
        return client.create_table(table)


def load_benchmarks_to_bigquery(
    dataframe: pd.DataFrame,
    config: ProjectConfig,
    write_disposition: str = "merge",
    client: Any | None = None,
) -> tuple[str, int]:
    bigquery = import_bigquery_module()
    if dataframe.empty:
        raise ValueError("Cannot load empty benchmark dataframe into BigQuery.")

    table_id = get_benchmarks_table_id(config)
    location = config.settings["bigquery"].get("location", "EU")
    client = client or bigquery.Client(
        project=config.environment.google_cloud_project,
        location=location,
    )
    schema = build_benchmark_schema()
    ensure_benchmarks_table(client, table_id)

    if write_disposition in {"append", "truncate"}:
        disposition = (
            bigquery.WriteDisposition.WRITE_APPEND
            if write_disposition == "append"
            else bigquery.WriteDisposition.WRITE_TRUNCATE
        )
        job_config = bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=disposition,
        )
        job = client.load_table_from_dataframe(
            dataframe,
            table_id,
            job_config=job_config,
            location=location,
        )
        job.result()
        return table_id, len(dataframe)

    return merge_benchmarks_to_bigquery(client, dataframe, table_id, schema, location)


def merge_benchmarks_to_bigquery(
    client: Any,
    dataframe: pd.DataFrame,
    table_id: str,
    schema: list[Any],
    location: str,
) -> tuple[str, int]:
    bigquery = import_bigquery_module()
    project, dataset, table = table_id.split(".")
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
    update_columns = [
        column
        for column in columns
        if column not in {"date", "benchmark_id", "component_id"}
    ]
    update_clause = ",\n        ".join(
        f"target.{column} = source.{column}" for column in update_columns
    )
    insert_columns = ", ".join(columns)
    insert_values = ", ".join(f"source.{column}" for column in columns)

    merge_sql = f"""
    MERGE `{table_id}` AS target
    USING `{temp_table_id}` AS source
    ON target.date = source.date
       AND target.benchmark_id = source.benchmark_id
       AND COALESCE(target.component_id, '') = COALESCE(source.component_id, '')
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
    configured_path = output_dir or config.settings["paths"]["benchmarks_raw"]
    path = Path(configured_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def write_outputs(
    benchmarks: pd.DataFrame,
    metadata: pd.DataFrame,
    output_dir: Path,
    run_date: datetime | None = None,
) -> BenchmarkIngestionResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = (run_date or datetime.now(UTC)).strftime(DATE_FORMAT)
    output_path = output_dir / f"benchmarks_{suffix}.csv"
    metadata_path = output_dir / f"benchmarks_metadata_{suffix}.csv"

    benchmarks.to_csv(output_path, index=False, encoding="utf-8", date_format="%Y-%m-%d")
    metadata.to_csv(metadata_path, index=False, encoding="utf-8")

    return BenchmarkIngestionResult(
        output_path=output_path,
        metadata_path=metadata_path,
        rows=len(benchmarks),
        benchmarks=benchmarks["benchmark_id"].nunique(),
    )


def ingest_benchmarks(args: argparse.Namespace) -> BenchmarkIngestionResult | None:
    config = load_project_config()
    index_config = build_index_config(config)
    start_date, end_date = resolve_benchmark_date_window(args, config)
    output_dir = resolve_output_dir(config, args.output_dir)

    commodities = select_benchmark_commodities(
        config=config,
        priorities=args.priorities,
        symbols=args.symbols,
        include_disabled=args.include_disabled,
    )
    selected_assets = build_selected_assets(commodities)

    if args.dry_run:
        print(
            pd.DataFrame(
                [
                    {
                        "commodity_id": asset_id,
                        "symbol": metadata["ticker"],
                        "priority": metadata["priority"],
                    }
                    for asset_id, metadata in selected_assets.items()
                ]
            ).to_string(index=False)
        )
        return None

    benchmark_source = YFINANCE_SOURCE
    if args.input_market_csv:
        raw_prices = load_price_panel_from_market_csv(
            csv_path=args.input_market_csv,
            selected_assets=selected_assets,
            price_field=index_config.price_field,
        )
        benchmark_source = raw_prices.attrs.get("source", "market_data_csv")
    elif args.prefer_market_data_fallback:
        fallback_path = resolve_market_data_fallback_path(config)
        LOGGER.info("Using market data fallback for benchmarks: %s", fallback_path)
        raw_prices = load_price_panel_from_market_csv(
            csv_path=fallback_path,
            selected_assets=selected_assets,
            price_field=index_config.price_field,
        )
        benchmark_source = raw_prices.attrs.get("source", "market_data_csv")
    else:
        try:
            raw_prices = download_price_panel(
                selected_assets=selected_assets,
                start_date=start_date,
                end_date=end_date,
                price_field=index_config.price_field,
            )
        except Exception:
            if not args.use_market_data_fallback:
                raise

            fallback_path = resolve_market_data_fallback_path(config)
            LOGGER.warning(
                "Benchmark Yahoo download failed; using market data fallback: %s",
                fallback_path,
            )
            raw_prices = load_price_panel_from_market_csv(
                csv_path=fallback_path,
                selected_assets=selected_assets,
                price_field=index_config.price_field,
            )
            benchmark_source = raw_prices.attrs.get("source", "market_data_csv")

    aligned_prices, _ = align_price_panel(
        raw_prices,
        selected_assets=selected_assets,
        max_forward_fill=index_config.max_forward_fill,
    )
    validate_benchmark_coverage(
        aligned_prices=aligned_prices,
        selected_assets=selected_assets,
        min_coverage_ratio=args.min_coverage_ratio,
    )
    benchmarks, metadata = build_benchmark_dataset(
        aligned_prices=aligned_prices,
        selected_assets=selected_assets,
        config=config,
        source=benchmark_source,
    )
    benchmarks, metadata = append_global_external_benchmark(
        benchmarks=benchmarks,
        metadata=metadata,
        config=config,
        start_date=start_date,
        end_date=end_date,
        skip_global_external=args.skip_global_external,
    )
    benchmarks = clean_benchmark_dataset(benchmarks)
    result = write_outputs(benchmarks, metadata, output_dir)

    LOGGER.info("Benchmark rows written: %s", result.rows)
    LOGGER.info("Benchmark CSV: %s", result.output_path)
    LOGGER.info("Benchmark metadata CSV: %s", result.metadata_path)

    if not args.skip_bigquery:
        LOGGER.info(
            "Loading %s benchmark rows into BigQuery with write_disposition=%s.",
            len(benchmarks),
            args.write_disposition,
        )
        table_id, loaded_rows = load_benchmarks_to_bigquery(
            dataframe=benchmarks,
            config=config,
            write_disposition=args.write_disposition,
        )
        result = BenchmarkIngestionResult(
            output_path=result.output_path,
            metadata_path=result.metadata_path,
            rows=result.rows,
            benchmarks=result.benchmarks,
            bigquery_table=table_id,
            bigquery_rows=loaded_rows,
        )
        LOGGER.info("BigQuery table loaded: %s", table_id)
        LOGGER.info("BigQuery rows processed: %s", loaded_rows)

    return result


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)
    ingest_benchmarks(args)


if __name__ == "__main__":
    main()
