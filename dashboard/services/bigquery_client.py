from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class BigQueryConnectionError(RuntimeError):
    """Raised when the dashboard cannot connect to BigQuery."""


@dataclass(frozen=True)
class BigQuerySettings:
    project_id: str
    location: str = "EU"
    marts_dataset: str = "mart"
    staging_dataset: str = "dbt_finance"
    maximum_bytes_billed: int = 1_000_000_000

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "BigQuerySettings":
        load_dotenv(env_file or PROJECT_ROOT / ".env")
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
        if not project_id:
            raise BigQueryConnectionError(
                "GOOGLE_CLOUD_PROJECT or GCP_PROJECT must be set to query BigQuery marts."
            )

        return cls(
            project_id=project_id,
            location=os.getenv("BIGQUERY_LOCATION", "EU"),
            marts_dataset=(
                os.getenv("BIGQUERY_MARTS_DATASET")
                or os.getenv("BIGQUERY_MART_DATASET")
                or "mart"
            ),
            staging_dataset=(
                os.getenv("BIGQUERY_STAGING_DATASET")
                or os.getenv("BIGQUERY_DBT_DATASET")
                or "dbt_finance"
            ),
            maximum_bytes_billed=int(os.getenv("BIGQUERY_MAX_BYTES_BILLED", "1000000000")),
        )


class BigQueryClient:
    def __init__(self, settings: BigQuerySettings | None = None) -> None:
        self.settings = settings or BigQuerySettings.from_env()
        try:
            from google.cloud import bigquery
        except ImportError as exc:
            raise BigQueryConnectionError(
                "google-cloud-bigquery is required. Install requirements/requirements.txt."
            ) from exc

        self._client = bigquery.Client(project=self.settings.project_id, location=self.settings.location)

    def table_id(self, table_name: str, dataset: str | None = None) -> str:
        safe_table_name = table_name.replace("`", "")
        safe_dataset = (dataset or self.settings.marts_dataset).replace("`", "")
        return f"`{self.settings.project_id}.{safe_dataset}.{safe_table_name}`"

    def query_dataframe(self, query: str) -> pd.DataFrame:
        try:
            from google.cloud import bigquery

            job_config = bigquery.QueryJobConfig(
                maximum_bytes_billed=self.settings.maximum_bytes_billed,
                labels={
                    "component": "streamlit",
                    "project": "elt-commodities",
                },
            )
            return self._client.query(query, job_config=job_config).to_dataframe()
        except Exception as exc:
            raise BigQueryConnectionError(format_bigquery_error(exc)) from exc

    def estimate_query_bytes(self, query: str) -> int:
        try:
            from google.cloud import bigquery

            job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
            query_job = self._client.query(query, job_config=job_config)
            return int(query_job.total_bytes_processed or 0)
        except Exception as exc:
            raise BigQueryConnectionError(f"BigQuery dry-run failed: {exc}") from exc


def format_bigquery_error(exc: Exception) -> str:
    message = str(exc)
    lower_message = message.lower()
    if "not found: table" in lower_message and ".mart_" in lower_message:
        return (
            "BigQuery query failed: table mart manquante. "
            "L'infrastructure Terraform crée seulement les datasets; les tables mart sont créées par dbt. "
            "Lance d'abord l'ingestion raw, puis `make dbt-run` pour créer les tables du dashboard. "
            f"Détail BigQuery: {message}"
        )
    return f"BigQuery query failed: {message}"
