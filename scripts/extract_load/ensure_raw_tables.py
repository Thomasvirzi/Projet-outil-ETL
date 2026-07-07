from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.extract_load.config import ProjectConfig, load_project_config
    from scripts.extract_load.ingest_benchmarks import BENCHMARK_SCHEMA
    from scripts.extract_load.ingest_commodities import MARKET_DATA_SCHEMA
    from scripts.extract_load.ingest_rss import NEWS_SCHEMA
    from scripts.nlp.compute_news_indicators import NEWS_FEATURES_SCHEMA
    from scripts.nlp.compute_relevance import RELEVANCE_SCHEMA
    from scripts.nlp.compute_sentiment import SENTIMENT_SCHEMA
    from scripts.nlp.create_embeddings import EMBEDDINGS_SCHEMA
except ModuleNotFoundError:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from scripts.extract_load.config import ProjectConfig, load_project_config
    from scripts.extract_load.ingest_benchmarks import BENCHMARK_SCHEMA
    from scripts.extract_load.ingest_commodities import MARKET_DATA_SCHEMA
    from scripts.extract_load.ingest_rss import NEWS_SCHEMA
    from scripts.nlp.compute_news_indicators import NEWS_FEATURES_SCHEMA
    from scripts.nlp.compute_relevance import RELEVANCE_SCHEMA
    from scripts.nlp.compute_sentiment import SENTIMENT_SCHEMA
    from scripts.nlp.create_embeddings import EMBEDDINGS_SCHEMA


LOGGER = logging.getLogger(__name__)

PIPELINE_LOGS_SCHEMA = [
    ("run_id", "STRING", "REQUIRED"),
    ("task_name", "STRING", "REQUIRED"),
    ("start_time", "TIMESTAMP", "NULLABLE"),
    ("end_time", "TIMESTAMP", "NULLABLE"),
    ("status", "STRING", "NULLABLE"),
    ("duration_seconds", "FLOAT", "NULLABLE"),
    ("rows_processed", "INTEGER", "NULLABLE"),
    ("error_message", "STRING", "NULLABLE"),
]

RAW_TABLE_SPECS = {
    "market_data_raw": {
        "schema": MARKET_DATA_SCHEMA,
        "partition_field": "date",
        "clustering_fields": ["symbol"],
    },
    "benchmarks_raw": {
        "schema": BENCHMARK_SCHEMA,
        "partition_field": "date",
        "clustering_fields": ["benchmark_id", "benchmark_type"],
    },
    "news_raw": {
        "schema": NEWS_SCHEMA,
        "partition_field": "published_at",
        "clustering_fields": ["source_id", "category"],
    },
    "news_embeddings_raw": {
        "schema": EMBEDDINGS_SCHEMA,
        "partition_field": "created_at",
        "clustering_fields": ["embedding_model"],
    },
    "news_sentiment_raw": {
        "schema": SENTIMENT_SCHEMA,
        "partition_field": "calculated_at",
        "clustering_fields": ["sentiment_model"],
    },
    "article_commodity_relevance_raw": {
        "schema": RELEVANCE_SCHEMA,
        "partition_field": "calculated_at",
        "clustering_fields": ["commodity_id", "is_relevant"],
    },
    "news_features_raw": {
        "schema": NEWS_FEATURES_SCHEMA,
        "partition_field": "date",
        "clustering_fields": ["commodity_id"],
    },
    "pipeline_logs_raw": {
        "schema": PIPELINE_LOGS_SCHEMA,
        "partition_field": "start_time",
        "clustering_fields": ["task_name", "status"],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ensure optional raw BigQuery tables exist.")
    parser.add_argument(
        "--tables",
        nargs="*",
        choices=sorted(RAW_TABLE_SPECS),
        help="Optional subset of raw table keys to ensure.",
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


def import_bigquery_module() -> Any:
    try:
        from google.cloud import bigquery
    except ImportError as error:
        raise RuntimeError(
            "google-cloud-bigquery is required to ensure raw BigQuery tables. "
            "Install dependencies with `make install`."
        ) from error
    return bigquery


def get_table_id(config: ProjectConfig, table_key: str) -> str:
    project_id = config.environment.google_cloud_project
    if not project_id:
        raise ValueError("GOOGLE_CLOUD_PROJECT is required to ensure raw tables.")

    dataset = config.settings["bigquery"]["raw_dataset"]
    table = config.settings["bigquery"]["tables"][table_key]
    return f"{project_id}.{dataset}.{table}"


def build_schema(schema_fields: list[tuple[str, str, str]]) -> list[Any]:
    bigquery = import_bigquery_module()
    return [
        bigquery.SchemaField(name, field_type, mode=mode)
        for name, field_type, mode in schema_fields
    ]


def ensure_table(client: Any, config: ProjectConfig, table_key: str) -> bool:
    bigquery = import_bigquery_module()
    spec = RAW_TABLE_SPECS[table_key]
    table_id = get_table_id(config, table_key)

    try:
        client.get_table(table_id)
        LOGGER.info("Raw table already exists: %s", table_id)
        return False
    except Exception:
        table = bigquery.Table(table_id, schema=build_schema(spec["schema"]))
        partition_field = spec.get("partition_field")
        if partition_field:
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field=partition_field,
            )
        clustering_fields = spec.get("clustering_fields")
        if clustering_fields:
            table.clustering_fields = clustering_fields

        LOGGER.info("Creating raw table: %s", table_id)
        client.create_table(table)
        return True


def ensure_raw_tables(table_keys: list[str] | None = None) -> int:
    bigquery = import_bigquery_module()
    config = load_project_config()
    location = config.settings["bigquery"].get("location", "EU")
    client = bigquery.Client(
        project=config.environment.google_cloud_project,
        location=location,
    )

    selected_table_keys = table_keys or list(RAW_TABLE_SPECS)
    created_count = 0
    for table_key in selected_table_keys:
        created_count += int(ensure_table(client, config, table_key))
    return created_count


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)
    created_count = ensure_raw_tables(args.tables)
    LOGGER.info("Raw table ensure complete. created=%s", created_count)


if __name__ == "__main__":
    main()
