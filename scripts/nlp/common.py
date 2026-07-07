from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from scripts.extract_load.config import ProjectConfig, load_project_config
except ModuleNotFoundError:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from scripts.extract_load.config import ProjectConfig, load_project_config


LOGGER = logging.getLogger(__name__)
DATE_FORMAT = "%Y%m%d"


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
            "google-cloud-bigquery is required to load NLP data into BigQuery. "
            "Install dependencies with `make install`."
        ) from error
    return bigquery


def get_raw_table_id(config: ProjectConfig, table_key: str) -> str:
    project_id = config.environment.google_cloud_project
    if not project_id:
        raise ValueError(f"GOOGLE_CLOUD_PROJECT is required to load {table_key}.")

    dataset = config.settings["bigquery"]["raw_dataset"]
    table = config.settings["bigquery"]["tables"][table_key]
    return f"{project_id}.{dataset}.{table}"


def resolve_output_dir(config: ProjectConfig, configured_path: str | None) -> Path:
    path = Path(configured_path or config.settings["paths"]["news_embeddings_processed"])
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_articles_from_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"News CSV not found: {path}")

    articles = pd.read_csv(path)
    required_columns = {"article_id", "title", "clean_text"}
    missing_columns = required_columns.difference(articles.columns)
    if missing_columns:
        raise ValueError(f"Missing news columns: {sorted(missing_columns)}")

    return articles


def read_table_to_dataframe(
    config: ProjectConfig,
    table_key: str,
    columns: list[str] | None = None,
    where_clause: str | None = None,
    client: Any | None = None,
) -> pd.DataFrame:
    bigquery = import_bigquery_module()
    table_id = get_raw_table_id(config, table_key)
    location = config.settings["bigquery"].get("location", "EU")
    client = client or bigquery.Client(
        project=config.environment.google_cloud_project,
        location=location,
    )

    select_clause = ", ".join(columns) if columns else "*"
    query = f"SELECT {select_clause} FROM `{table_id}`"
    if where_clause:
        query += f" WHERE {where_clause}"

    return client.query(query, location=location).to_dataframe()


def load_dataframe_to_bigquery(
    dataframe: pd.DataFrame,
    config: ProjectConfig,
    table_key: str,
    schema_fields: list[tuple[str, str, str]],
    unique_keys: list[str],
    write_disposition: str = "merge",
    partition_field: str | None = None,
    clustering_fields: list[str] | None = None,
    client: Any | None = None,
) -> tuple[str, int]:
    bigquery = import_bigquery_module()
    if dataframe.empty:
        raise ValueError(f"Cannot load empty dataframe into {table_key}.")

    table_id = get_raw_table_id(config, table_key)
    location = config.settings["bigquery"].get("location", "EU")
    client = client or bigquery.Client(
        project=config.environment.google_cloud_project,
        location=location,
    )
    schema = [
        bigquery.SchemaField(name, field_type, mode=mode)
        for name, field_type, mode in schema_fields
    ]
    table = bigquery.Table(table_id, schema=schema)
    if partition_field:
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field=partition_field,
        )
    if clustering_fields:
        table.clustering_fields = clustering_fields

    try:
        client.get_table(table_id)
    except Exception:
        LOGGER.info("Creating BigQuery table %s.", table_id)
        client.create_table(table)

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

    return merge_dataframe_to_bigquery(
        client=client,
        dataframe=dataframe,
        table_id=table_id,
        schema=schema,
        unique_keys=unique_keys,
        location=location,
    )


def merge_dataframe_to_bigquery(
    client: Any,
    dataframe: pd.DataFrame,
    table_id: str,
    schema: list[Any],
    unique_keys: list[str],
    location: str,
) -> tuple[str, int]:
    bigquery = import_bigquery_module()
    project, dataset, table = table_id.split(".")
    suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    temp_table_id = f"{project}.{dataset}._tmp_{table}_{suffix}"
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
    update_columns = [column for column in columns if column not in set(unique_keys)]
    update_clause = ",\n        ".join(
        f"target.{column} = source.{column}" for column in update_columns
    )
    insert_columns = ", ".join(columns)
    insert_values = ", ".join(f"source.{column}" for column in columns)
    join_clause = " AND ".join(
        f"target.{column} = source.{column}" for column in unique_keys
    )

    merge_sql = f"""
    MERGE `{table_id}` AS target
    USING `{temp_table_id}` AS source
    ON {join_clause}
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


def build_article_text(row: pd.Series) -> str:
    title = str(row.get("title", "") or "").strip()
    clean_text = str(row.get("clean_text", "") or "").strip()
    if title and clean_text and title.lower() not in clean_text.lower():
        return f"{title}. {clean_text}"
    return clean_text or title


def embedding_to_json(embedding: list[float] | np.ndarray) -> str:
    values = np.asarray(embedding, dtype=float).tolist()
    return json.dumps(values, separators=(",", ":"))


def embedding_from_json(value: str | list[float]) -> np.ndarray:
    if isinstance(value, list):
        return np.asarray(value, dtype=float)
    return np.asarray(json.loads(value), dtype=float)


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_norm = np.linalg.norm(left)
    right_norm = np.linalg.norm(right)
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return float(np.dot(left, right) / (left_norm * right_norm))


def mock_embedding(text: str, dimension: int = 8) -> list[float]:
    digest = np.frombuffer(text.encode("utf-8"), dtype=np.uint8)
    vector = np.zeros(dimension, dtype=float)
    for index, value in enumerate(digest):
        vector[index % dimension] += float(value)
    norm = np.linalg.norm(vector)
    if norm:
        vector = vector / norm
    return vector.tolist()


def load_project() -> ProjectConfig:
    return load_project_config()
