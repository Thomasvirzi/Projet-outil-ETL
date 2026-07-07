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
        configure_logging,
        cosine_similarity,
        embedding_from_json,
        embedding_to_json,
        load_dataframe_to_bigquery,
        load_project,
        mock_embedding,
        read_table_to_dataframe,
        resolve_output_dir,
    )
except ModuleNotFoundError:
    import sys

    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from scripts.nlp.common import (
        DATE_FORMAT,
        configure_logging,
        cosine_similarity,
        embedding_from_json,
        embedding_to_json,
        load_dataframe_to_bigquery,
        load_project,
        mock_embedding,
        read_table_to_dataframe,
        resolve_output_dir,
    )


RELEVANCE_SCHEMA = [
    ("article_id", "STRING", "REQUIRED"),
    ("commodity_id", "STRING", "REQUIRED"),
    ("commodity_symbol", "STRING", "NULLABLE"),
    ("commodity_name", "STRING", "NULLABLE"),
    ("commodity_description", "STRING", "NULLABLE"),
    ("similarity_score", "FLOAT", "NULLABLE"),
    ("is_relevant", "BOOLEAN", "NULLABLE"),
    ("relevance_threshold", "FLOAT", "NULLABLE"),
    ("embedding_model", "STRING", "NULLABLE"),
    ("calculated_at", "TIMESTAMP", "NULLABLE"),
]


@dataclass(frozen=True)
class RelevanceResult:
    output_path: Path
    rows: int
    relevant_rows: int
    bigquery_table: str | None = None
    bigquery_rows: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute article-to-commodity relevance with cosine similarity."
    )
    parser.add_argument("--input-embeddings-csv", type=Path, help="Local embeddings CSV.")
    parser.add_argument("--output-dir", help="Output directory for relevance CSV.")
    parser.add_argument("--model-name", help="Embedding model used for commodity texts.")
    parser.add_argument(
        "--threshold",
        type=float,
        help="Override settings.nlp.relevance_threshold.",
    )
    parser.add_argument(
        "--mock-embeddings",
        action="store_true",
        help="Use deterministic lightweight commodity embeddings for tests.",
    )
    parser.add_argument(
        "--only-relevant",
        action="store_true",
        help="Output only rows with similarity above threshold.",
    )
    parser.add_argument(
        "--skip-bigquery",
        action="store_true",
        help="Write local CSV but do not load raw.article_commodity_relevance_raw.",
    )
    parser.add_argument(
        "--write-disposition",
        default="merge",
        choices=["merge", "append", "truncate"],
        help="BigQuery write mode. Default: merge on article_id + commodity_id + model.",
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
            "sentence-transformers is required for relevance. "
            "Install dependencies with `make install`."
        ) from error
    return SentenceTransformer(model_name)


def load_article_embeddings(args: argparse.Namespace) -> pd.DataFrame:
    config = load_project()
    if args.input_embeddings_csv:
        return pd.read_csv(args.input_embeddings_csv)

    return read_table_to_dataframe(
        config=config,
        table_key="news_embeddings_raw",
        columns=["article_id", "embedding", "embedding_model"],
    )


def build_commodity_descriptions(config: Any) -> pd.DataFrame:
    rows = []
    for commodity in config.enabled_commodities:
        description_parts = [
            commodity.get("name", ""),
            commodity.get("label_fr", ""),
            commodity.get("category", ""),
            commodity.get("rss_query", ""),
            f"Yahoo Finance symbol {commodity.get('symbol', '')}",
        ]
        description = ". ".join(part for part in description_parts if part)
        rows.append(
            {
                "commodity_id": commodity["commodity_id"],
                "commodity_symbol": commodity["symbol"],
                "commodity_name": commodity["name"],
                "commodity_description": description,
            }
        )

    return pd.DataFrame(rows)


def encode_commodity_descriptions(
    commodities: pd.DataFrame,
    model_name: str,
    model: Any | None = None,
    mock_embeddings: bool = False,
) -> pd.DataFrame:
    descriptions = commodities["commodity_description"].tolist()
    if mock_embeddings:
        embeddings = [mock_embedding(description) for description in descriptions]
    else:
        model = model or load_embedding_model(model_name)
        embeddings = model.encode(descriptions, show_progress_bar=False).tolist()

    encoded = commodities.copy()
    encoded["embedding"] = [embedding_to_json(embedding) for embedding in embeddings]
    return encoded


def compute_relevance_dataframe(
    article_embeddings: pd.DataFrame,
    commodity_embeddings: pd.DataFrame,
    threshold: float,
    only_relevant: bool = False,
) -> pd.DataFrame:
    if article_embeddings.empty or commodity_embeddings.empty:
        return pd.DataFrame(columns=[field[0] for field in RELEVANCE_SCHEMA])

    calculated_at = datetime.now(UTC)
    rows = []
    for article in article_embeddings.itertuples(index=False):
        article_vector = embedding_from_json(article.embedding)
        embedding_model = getattr(article, "embedding_model", None)
        for commodity in commodity_embeddings.itertuples(index=False):
            commodity_vector = embedding_from_json(commodity.embedding)
            similarity = cosine_similarity(article_vector, commodity_vector)
            is_relevant = similarity >= threshold
            if only_relevant and not is_relevant:
                continue
            rows.append(
                {
                    "article_id": article.article_id,
                    "commodity_id": commodity.commodity_id,
                    "commodity_symbol": commodity.commodity_symbol,
                    "commodity_name": commodity.commodity_name,
                    "commodity_description": commodity.commodity_description,
                    "similarity_score": similarity,
                    "is_relevant": is_relevant,
                    "relevance_threshold": threshold,
                    "embedding_model": embedding_model,
                    "calculated_at": calculated_at,
                }
            )

    return pd.DataFrame(rows)


def write_outputs(
    relevance: pd.DataFrame,
    output_dir: Path,
    run_date: datetime | None = None,
) -> Path:
    suffix = (run_date or datetime.now(UTC)).strftime(DATE_FORMAT)
    output_path = output_dir / f"article_commodity_relevance_{suffix}.csv"
    relevance.to_csv(output_path, index=False, encoding="utf-8")
    return output_path


def run_relevance(args: argparse.Namespace) -> RelevanceResult:
    config = load_project()
    threshold = (
        args.threshold
        if args.threshold is not None
        else float(config.settings["nlp"]["relevance_threshold"])
    )
    model_name = args.model_name or config.settings["nlp"]["embedding_model"]
    output_dir = resolve_output_dir(config, args.output_dir)

    article_embeddings = load_article_embeddings(args)
    commodities = build_commodity_descriptions(config)
    commodity_embeddings = encode_commodity_descriptions(
        commodities=commodities,
        model_name=model_name,
        mock_embeddings=args.mock_embeddings,
    )
    relevance = compute_relevance_dataframe(
        article_embeddings=article_embeddings,
        commodity_embeddings=commodity_embeddings,
        threshold=threshold,
        only_relevant=args.only_relevant,
    )
    output_path = write_outputs(relevance, output_dir)
    result = RelevanceResult(
        output_path=output_path,
        rows=len(relevance),
        relevant_rows=int(relevance["is_relevant"].sum()) if not relevance.empty else 0,
    )

    if not relevance.empty and not args.skip_bigquery:
        table_id, loaded_rows = load_dataframe_to_bigquery(
            dataframe=relevance,
            config=config,
            table_key="article_commodity_relevance_raw",
            schema_fields=RELEVANCE_SCHEMA,
            unique_keys=["article_id", "commodity_id", "embedding_model"],
            write_disposition=args.write_disposition,
            partition_field="calculated_at",
            clustering_fields=["commodity_id", "is_relevant"],
        )
        result = RelevanceResult(
            output_path=result.output_path,
            rows=result.rows,
            relevant_rows=result.relevant_rows,
            bigquery_table=table_id,
            bigquery_rows=loaded_rows,
        )

    return result


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)
    run_relevance(args)


if __name__ == "__main__":
    main()
