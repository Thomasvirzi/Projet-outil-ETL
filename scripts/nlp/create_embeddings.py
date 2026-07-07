from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from scripts.nlp.common import (
        DATE_FORMAT,
        build_article_text,
        configure_logging,
        embedding_to_json,
        load_dataframe_to_bigquery,
        load_project,
        mock_embedding,
        read_articles_from_csv,
        read_table_to_dataframe,
        resolve_output_dir,
    )
except ModuleNotFoundError:
    import sys

    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from scripts.nlp.common import (
        DATE_FORMAT,
        build_article_text,
        configure_logging,
        embedding_to_json,
        load_dataframe_to_bigquery,
        load_project,
        mock_embedding,
        read_articles_from_csv,
        read_table_to_dataframe,
        resolve_output_dir,
    )


EMBEDDINGS_SCHEMA = [
    ("article_id", "STRING", "REQUIRED"),
    ("embedding", "STRING", "REQUIRED"),
    ("embedding_dimension", "INTEGER", "NULLABLE"),
    ("embedding_model", "STRING", "REQUIRED"),
    ("embedding_model_version", "STRING", "NULLABLE"),
    ("created_at", "TIMESTAMP", "NULLABLE"),
]


@dataclass(frozen=True)
class EmbeddingResult:
    output_path: Path
    rows: int
    model_name: str
    bigquery_table: str | None = None
    bigquery_rows: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create article embeddings.")
    parser.add_argument("--input-news-csv", type=Path, help="Local news CSV input.")
    parser.add_argument(
        "--existing-embeddings-csv",
        type=Path,
        help="Optional existing embeddings CSV to avoid recalculation locally.",
    )
    parser.add_argument("--output-dir", help="Output directory for embeddings CSV.")
    parser.add_argument("--model-name", help="Override settings.nlp.embedding_model.")
    parser.add_argument(
        "--mock-embeddings",
        action="store_true",
        help="Use deterministic lightweight embeddings for tests/offline checks.",
    )
    parser.add_argument(
        "--skip-bigquery",
        action="store_true",
        help="Write local CSV but do not load raw.news_embeddings_raw.",
    )
    parser.add_argument(
        "--write-disposition",
        default="merge",
        choices=["merge", "append", "truncate"],
        help="BigQuery write mode. Default: merge on article_id + embedding_model.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print pending articles without generating embeddings.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level.",
    )
    return parser.parse_args()


def load_embedding_model(model_name: str) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise RuntimeError(
            "sentence-transformers is required for embeddings. "
            "Install dependencies with `make install`."
        ) from error
    return SentenceTransformer(model_name)


def get_model_version(model: Any, model_name: str) -> str:
    modules_config = getattr(model, "_modules_config", None)
    if modules_config:
        return str(modules_config)
    return model_name


def load_articles(args: argparse.Namespace) -> pd.DataFrame:
    config = load_project()
    if args.input_news_csv:
        return read_articles_from_csv(args.input_news_csv)

    return read_table_to_dataframe(
        config=config,
        table_key="news_raw",
        columns=["article_id", "title", "clean_text", "published_at"],
    )


def load_existing_embedding_keys(
    args: argparse.Namespace,
    model_name: str,
) -> set[tuple[str, str]]:
    config = load_project()
    if args.existing_embeddings_csv:
        existing = pd.read_csv(args.existing_embeddings_csv)
    elif args.skip_bigquery:
        return set()
    else:
        try:
            existing = read_table_to_dataframe(
                config=config,
                table_key="news_embeddings_raw",
                columns=["article_id", "embedding_model"],
                where_clause=f"embedding_model = '{model_name}'",
            )
        except Exception:
            return set()

    if existing.empty:
        return set()

    return set(zip(existing["article_id"], existing["embedding_model"], strict=False))


def filter_pending_articles(
    articles: pd.DataFrame,
    existing_keys: set[tuple[str, str]],
    model_name: str,
) -> pd.DataFrame:
    if not existing_keys:
        return articles.drop_duplicates(subset=["article_id"]).copy()

    pending = articles[
        ~articles["article_id"].apply(lambda article_id: (article_id, model_name) in existing_keys)
    ]
    return pending.drop_duplicates(subset=["article_id"]).copy()


def create_embedding_dataframe(
    articles: pd.DataFrame,
    model_name: str,
    model: Any | None = None,
    mock_embeddings: bool = False,
) -> pd.DataFrame:
    if articles.empty:
        return pd.DataFrame(columns=[field[0] for field in EMBEDDINGS_SCHEMA])

    texts = articles.apply(build_article_text, axis=1).tolist()

    if mock_embeddings:
        embeddings = [mock_embedding(text) for text in texts]
        model_version = f"{model_name}:mock"
    else:
        model = model or load_embedding_model(model_name)
        embeddings = model.encode(texts, show_progress_bar=False).tolist()
        model_version = get_model_version(model, model_name)

    created_at = datetime.now(UTC)
    rows = []
    for article_id, embedding in zip(articles["article_id"], embeddings, strict=False):
        rows.append(
            {
                "article_id": article_id,
                "embedding": embedding_to_json(embedding),
                "embedding_dimension": len(embedding),
                "embedding_model": model_name,
                "embedding_model_version": model_version,
                "created_at": created_at,
            }
        )

    return pd.DataFrame(rows)


def write_outputs(
    embeddings: pd.DataFrame,
    output_dir: Path,
    run_date: datetime | None = None,
) -> Path:
    suffix = (run_date or datetime.now(UTC)).strftime(DATE_FORMAT)
    output_path = output_dir / f"news_embeddings_{suffix}.csv"
    embeddings.to_csv(output_path, index=False, encoding="utf-8")
    return output_path


def run_embeddings(args: argparse.Namespace) -> EmbeddingResult | None:
    config = load_project()
    model_name = args.model_name or config.settings["nlp"]["embedding_model"]
    output_dir = resolve_output_dir(config, args.output_dir)
    articles = load_articles(args)
    existing_keys = load_existing_embedding_keys(args, model_name)
    pending_articles = filter_pending_articles(articles, existing_keys, model_name)

    if args.dry_run:
        print(pending_articles[["article_id", "title"]].to_string(index=False))
        return None

    embeddings = create_embedding_dataframe(
        articles=pending_articles,
        model_name=model_name,
        mock_embeddings=args.mock_embeddings,
    )
    output_path = write_outputs(embeddings, output_dir)
    result = EmbeddingResult(
        output_path=output_path,
        rows=len(embeddings),
        model_name=model_name,
    )

    if not embeddings.empty and not args.skip_bigquery:
        table_id, loaded_rows = load_dataframe_to_bigquery(
            dataframe=embeddings,
            config=config,
            table_key="news_embeddings_raw",
            schema_fields=EMBEDDINGS_SCHEMA,
            unique_keys=["article_id", "embedding_model"],
            write_disposition=args.write_disposition,
            partition_field="created_at",
            clustering_fields=["embedding_model"],
        )
        result = EmbeddingResult(
            output_path=result.output_path,
            rows=result.rows,
            model_name=result.model_name,
            bigquery_table=table_id,
            bigquery_rows=loaded_rows,
        )

    return result


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)
    run_embeddings(args)


if __name__ == "__main__":
    main()
