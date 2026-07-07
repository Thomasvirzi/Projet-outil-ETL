from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import pandas as pd
import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from scripts.extract_load.config import ProjectConfig, load_project_config
except ModuleNotFoundError:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from scripts.extract_load.config import ProjectConfig, load_project_config


LOGGER = logging.getLogger(__name__)
DATE_FORMAT = "%Y%m%d"
DEFAULT_TIMEOUT_SECONDS = 20
USER_AGENT = "elt-commodities-pipeline/1.0"

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
HTML_TAG_PATTERN = re.compile(r"<[A-Za-z!/][^>]*>")
HTML_ENTITY_PATTERN = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]+|#[0-9]+|#x[0-9A-Fa-f]+);")

NEWS_SCHEMA = [
    ("article_id", "STRING", "REQUIRED"),
    ("source_id", "STRING", "NULLABLE"),
    ("feed_id", "STRING", "NULLABLE"),
    ("source", "STRING", "NULLABLE"),
    ("feed_name", "STRING", "NULLABLE"),
    ("category", "STRING", "NULLABLE"),
    ("language", "STRING", "NULLABLE"),
    ("priority", "INTEGER", "NULLABLE"),
    ("quality", "STRING", "NULLABLE"),
    ("title", "STRING", "REQUIRED"),
    ("url", "STRING", "NULLABLE"),
    ("canonical_url", "STRING", "NULLABLE"),
    ("published_at", "TIMESTAMP", "NULLABLE"),
    ("summary", "STRING", "NULLABLE"),
    ("clean_text", "STRING", "NULLABLE"),
    ("content_hash", "STRING", "REQUIRED"),
    ("raw_content_hash", "STRING", "NULLABLE"),
    ("fetched_at", "TIMESTAMP", "NULLABLE"),
    ("ingested_at", "TIMESTAMP", "NULLABLE"),
]


@dataclass(frozen=True)
class RssIngestionResult:
    output_path: Path
    errors_path: Path | None
    rows: int
    feeds: int
    bigquery_table: str | None = None
    bigquery_rows: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest configured RSS feeds into raw.news_raw."
    )
    parser.add_argument(
        "--source-ids",
        nargs="*",
        help="Optional source_id filter, for example spglobal_commodity_insights.",
    )
    parser.add_argument(
        "--feed-ids",
        nargs="*",
        help="Optional feed_id filter, for example investing_commodities_news.",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include feeds marked enabled: false.",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory. Defaults to settings.paths.news_raw.",
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
        help="BigQuery write mode. Default: merge on article_id.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print selected RSS feeds without fetching them.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Do not fail if no article row is written.",
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


def select_rss_sources(
    config: ProjectConfig,
    source_ids: list[str] | None = None,
    feed_ids: list[str] | None = None,
    include_disabled: bool = False,
) -> list[dict[str, Any]]:
    sources = config.rss_sources.get("rss_sources", [])

    if not include_disabled:
        sources = [source for source in sources if source.get("enabled", True)]

    if source_ids:
        allowed_source_ids = set(source_ids)
        sources = [
            source for source in sources if source.get("source_id") in allowed_source_ids
        ]

    if feed_ids:
        allowed_feed_ids = set(feed_ids)
        sources = [
            source for source in sources if source.get("feed_id") in allowed_feed_ids
        ]

    if not sources:
        raise ValueError("No RSS feed selected for ingestion.")

    validate_rss_sources(sources)
    return sources


def validate_rss_sources(sources: list[dict[str, Any]]) -> None:
    required_fields = ["source_id", "feed_id", "name", "source_name", "url"]

    for source in sources:
        missing_fields = [field for field in required_fields if not source.get(field)]
        if missing_fields:
            raise ValueError(
                f"RSS source {source!r} is missing fields: "
                + ", ".join(missing_fields)
            )

    feed_ids = [source["feed_id"] for source in sources]
    if len(feed_ids) != len(set(feed_ids)):
        raise ValueError("RSS feed_id values must be unique.")


def clean_html_text(value: str | None) -> str:
    if not value:
        return ""

    string_value = str(value)
    if not HTML_TAG_PATTERN.search(string_value) and not HTML_ENTITY_PATTERN.search(string_value):
        return " ".join(string_value.split())

    soup = BeautifulSoup(string_value, "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split())


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None

    parts = urlsplit(url.strip())
    query_items = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in TRACKING_QUERY_KEYS:
            continue
        if any(lowered.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        query_items.append((key, value))

    normalized_query = urlencode(query_items, doseq=True)
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            normalized_query,
            "",
        )
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_entry_datetime(entry: Any) -> datetime | None:
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if not value:
            continue
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except (TypeError, ValueError):
            continue

    return None


def get_entry_raw_content(entry: Any) -> str:
    content = entry.get("content")
    if content:
        first_content = content[0]
        if isinstance(first_content, dict):
            return first_content.get("value", "") or ""
        return getattr(first_content, "value", "") or ""

    return entry.get("summary", "") or entry.get("description", "") or ""


def normalize_feed_entry(
    entry: Any,
    source: dict[str, Any],
    fetched_at: datetime,
) -> dict[str, Any]:
    title = clean_html_text(entry.get("title", ""))
    raw_content = get_entry_raw_content(entry)
    summary = clean_html_text(entry.get("summary", ""))
    clean_text = clean_html_text(raw_content or summary)
    url = entry.get("link")
    canonical_url = canonicalize_url(url)
    published_at = parse_entry_datetime(entry)

    article_identity = "|".join(
        [
            source["source_id"],
            canonical_url or "",
            title.lower(),
            published_at.isoformat() if published_at else "",
        ]
    )
    content_identity = "|".join([title.lower(), clean_text.lower()])

    return {
        "article_id": sha256_text(article_identity),
        "source_id": source["source_id"],
        "feed_id": source["feed_id"],
        "source": source["source_name"],
        "feed_name": source["name"],
        "category": source.get("category"),
        "language": source.get("language"),
        "priority": source.get("priority"),
        "quality": source.get("quality"),
        "title": title,
        "url": url,
        "canonical_url": canonical_url,
        "published_at": published_at,
        "summary": summary,
        "clean_text": clean_text,
        "content_hash": sha256_text(content_identity),
        "raw_content_hash": sha256_text(raw_content or summary or title),
        "fetched_at": fetched_at,
        "ingested_at": datetime.now(UTC),
    }


def parse_feed_content(
    content: bytes | str,
    source: dict[str, Any],
    fetched_at: datetime | None = None,
) -> pd.DataFrame:
    fetched_at = fetched_at or datetime.now(UTC)
    parsed_feed = feedparser.parse(content)
    rows = [
        normalize_feed_entry(entry, source=source, fetched_at=fetched_at)
        for entry in parsed_feed.entries
    ]
    return pd.DataFrame(rows)


def normalize_article_frame_for_concat(articles: pd.DataFrame) -> pd.DataFrame:
    normalized = articles.copy()
    for column in get_news_columns():
        if column not in normalized.columns:
            normalized[column] = None
    return normalized[get_news_columns()].astype("object")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    reraise=True,
)
def fetch_feed_content(
    url: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    session: requests.Session | None = None,
) -> bytes:
    session = session or requests.Session()
    response = session.get(
        url,
        timeout=timeout_seconds,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return response.content


def fetch_and_parse_feed(
    source: dict[str, Any],
    session: requests.Session | None = None,
) -> tuple[pd.DataFrame, dict[str, Any] | None]:
    fetched_at = datetime.now(UTC)

    try:
        content = fetch_feed_content(source["url"], session=session)
        articles = parse_feed_content(content, source=source, fetched_at=fetched_at)
        return articles, None
    except Exception as error:
        LOGGER.warning("RSS feed failed: %s | %s", source["url"], error)
        LOGGER.debug("RSS feed failure details for %s.", source["url"], exc_info=True)
        return pd.DataFrame(), {
            "source_id": source.get("source_id"),
            "feed_id": source.get("feed_id"),
            "feed_name": source.get("name"),
            "url": source.get("url"),
            "error": str(error),
            "fetched_at": fetched_at.isoformat(),
        }


def clean_news_dataframe(articles: pd.DataFrame) -> pd.DataFrame:
    if articles.empty:
        return articles

    cleaned = articles.copy()
    cleaned["title"] = cleaned["title"].fillna("").astype(str).str.strip()
    cleaned["clean_text"] = cleaned["clean_text"].fillna("").astype(str).str.strip()
    cleaned["published_at"] = pd.to_datetime(
        cleaned["published_at"], utc=True, errors="coerce"
    )
    cleaned["fetched_at"] = pd.to_datetime(cleaned["fetched_at"], utc=True)
    cleaned["ingested_at"] = pd.to_datetime(cleaned["ingested_at"], utc=True)

    cleaned = cleaned[cleaned["title"].ne("")]
    cleaned = cleaned.dropna(subset=["article_id", "content_hash"])
    cleaned = cleaned.drop_duplicates(subset=["article_id"], keep="last")
    cleaned = cleaned.drop_duplicates(subset=["content_hash"], keep="last")

    return cleaned[get_news_columns()].sort_values(
        ["published_at", "source", "title"],
        na_position="last",
    )


def get_news_columns() -> list[str]:
    return [field[0] for field in NEWS_SCHEMA]


def import_bigquery_module() -> Any:
    try:
        from google.cloud import bigquery
    except ImportError as error:
        raise RuntimeError(
            "google-cloud-bigquery is required to load RSS data into BigQuery. "
            "Install dependencies with `make install`."
        ) from error
    return bigquery


def build_news_schema() -> list[Any]:
    bigquery = import_bigquery_module()
    return [
        bigquery.SchemaField(name, field_type, mode=mode)
        for name, field_type, mode in NEWS_SCHEMA
    ]


def get_news_table_id(config: ProjectConfig) -> str:
    project_id = config.environment.google_cloud_project
    if not project_id:
        raise ValueError("GOOGLE_CLOUD_PROJECT is required to load RSS news.")

    dataset = config.settings["bigquery"]["raw_dataset"]
    table = config.settings["bigquery"]["tables"]["news_raw"]
    return f"{project_id}.{dataset}.{table}"


def prepare_bigquery_dataframe(articles: pd.DataFrame) -> pd.DataFrame:
    dataframe = articles.copy()
    for column in get_news_columns():
        if column not in dataframe.columns:
            dataframe[column] = None

    dataframe["published_at"] = pd.to_datetime(
        dataframe["published_at"], utc=True, errors="coerce"
    )
    dataframe["fetched_at"] = pd.to_datetime(dataframe["fetched_at"], utc=True)
    dataframe["ingested_at"] = pd.to_datetime(dataframe["ingested_at"], utc=True)
    return dataframe[get_news_columns()]


def ensure_news_table(client: Any, table_id: str) -> Any:
    bigquery = import_bigquery_module()
    table = bigquery.Table(table_id, schema=build_news_schema())
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="published_at",
    )
    table.clustering_fields = ["source_id", "category"]

    try:
        return client.get_table(table_id)
    except Exception:
        LOGGER.info("Creating BigQuery table %s.", table_id)
        return client.create_table(table)


def load_news_to_bigquery(
    articles: pd.DataFrame,
    config: ProjectConfig,
    write_disposition: str = "merge",
    client: Any | None = None,
) -> tuple[str, int]:
    bigquery = import_bigquery_module()
    if articles.empty:
        raise ValueError("Cannot load empty RSS dataframe into BigQuery.")

    table_id = get_news_table_id(config)
    location = config.settings["bigquery"].get("location", "EU")
    client = client or bigquery.Client(
        project=config.environment.google_cloud_project,
        location=location,
    )
    dataframe = prepare_bigquery_dataframe(articles)
    schema = build_news_schema()
    ensure_news_table(client, table_id)

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

    return merge_news_to_bigquery(client, dataframe, table_id, schema, location)


def merge_news_to_bigquery(
    client: Any,
    dataframe: pd.DataFrame,
    table_id: str,
    schema: list[Any],
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
    update_columns = [column for column in columns if column != "article_id"]
    update_clause = ",\n        ".join(
        f"target.{column} = source.{column}" for column in update_columns
    )
    insert_columns = ", ".join(columns)
    insert_values = ", ".join(f"source.{column}" for column in columns)

    merge_sql = f"""
    MERGE `{table_id}` AS target
    USING `{temp_table_id}` AS source
    ON target.article_id = source.article_id
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
    configured_path = output_dir or config.settings["paths"]["news_raw"]
    path = Path(configured_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def write_outputs(
    articles: pd.DataFrame,
    errors: pd.DataFrame,
    output_dir: Path,
    run_date: datetime | None = None,
) -> RssIngestionResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = (run_date or datetime.now(UTC)).strftime(DATE_FORMAT)
    output_path = output_dir / f"news_{suffix}.csv"
    errors_path = output_dir / f"news_errors_{suffix}.csv" if not errors.empty else None

    articles.to_csv(output_path, index=False, encoding="utf-8")
    if errors_path:
        errors.to_csv(errors_path, index=False, encoding="utf-8")

    return RssIngestionResult(
        output_path=output_path,
        errors_path=errors_path,
        rows=len(articles),
        feeds=articles["feed_id"].nunique() if "feed_id" in articles else 0,
    )


def ingest_rss(args: argparse.Namespace) -> RssIngestionResult | None:
    config = load_project_config()
    output_dir = resolve_output_dir(config, args.output_dir)
    sources = select_rss_sources(
        config=config,
        source_ids=args.source_ids,
        feed_ids=args.feed_ids,
        include_disabled=args.include_disabled,
    )

    if args.dry_run:
        print(
            pd.DataFrame(sources)[
                ["source_id", "feed_id", "name", "url", "priority", "enabled"]
            ].to_string(index=False)
        )
        return None

    article_frames = []
    errors = []
    session = requests.Session()
    for source in sources:
        LOGGER.info("Fetching RSS feed %s.", source["url"])
        articles, error = fetch_and_parse_feed(source, session=session)
        if not articles.empty:
            article_frames.append(normalize_article_frame_for_concat(articles))
        if error:
            errors.append(error)

    raw_articles = (
        pd.concat(article_frames, ignore_index=True)
        if article_frames
        else pd.DataFrame(columns=get_news_columns())
    )
    articles = clean_news_dataframe(raw_articles)
    errors_df = pd.DataFrame(errors)
    result = write_outputs(articles, errors_df, output_dir)

    LOGGER.info("RSS articles written: %s", result.rows)
    LOGGER.info("RSS CSV: %s", result.output_path)
    if result.errors_path:
        LOGGER.warning("RSS errors CSV: %s", result.errors_path)

    if result.rows == 0 and not args.allow_empty:
        raise RuntimeError("No RSS article rows were written.")

    if result.rows > 0 and not args.skip_bigquery:
        table_id, loaded_rows = load_news_to_bigquery(
            articles=articles,
            config=config,
            write_disposition=args.write_disposition,
        )
        result = RssIngestionResult(
            output_path=result.output_path,
            errors_path=result.errors_path,
            rows=result.rows,
            feeds=result.feeds,
            bigquery_table=table_id,
            bigquery_rows=loaded_rows,
        )
        LOGGER.info("BigQuery table loaded: %s", table_id)
        LOGGER.info("BigQuery rows processed: %s", loaded_rows)

    return result


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)
    ingest_rss(args)


if __name__ == "__main__":
    main()
