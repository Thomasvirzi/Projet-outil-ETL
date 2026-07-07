from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from scripts.nlp.common import (
        DATE_FORMAT,
        build_article_text,
        configure_logging,
        load_dataframe_to_bigquery,
        load_project,
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
        load_dataframe_to_bigquery,
        load_project,
        read_articles_from_csv,
        read_table_to_dataframe,
        resolve_output_dir,
    )


SENTIMENT_SCHEMA = [
    ("article_id", "STRING", "REQUIRED"),
    ("positive_probability", "FLOAT", "NULLABLE"),
    ("neutral_probability", "FLOAT", "NULLABLE"),
    ("negative_probability", "FLOAT", "NULLABLE"),
    ("sentiment_score", "FLOAT", "NULLABLE"),
    ("novelty_score", "FLOAT", "NULLABLE"),
    ("sentiment_model", "STRING", "NULLABLE"),
    ("sentiment_model_version", "STRING", "NULLABLE"),
    ("calculated_at", "TIMESTAMP", "NULLABLE"),
]

TOKEN_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9_+-]{2,}")


@dataclass(frozen=True)
class SentimentResult:
    output_path: Path
    rows: int
    model_name: str
    bigquery_table: str | None = None
    bigquery_rows: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute FinBERT sentiment for news.")
    parser.add_argument("--input-news-csv", type=Path, help="Local news CSV input.")
    parser.add_argument("--output-dir", help="Output directory for sentiment CSV.")
    parser.add_argument("--model-name", help="Override settings.nlp.sentiment_model.")
    parser.add_argument(
        "--mock-sentiment",
        action="store_true",
        help="Use deterministic keyword sentiment for tests/offline checks.",
    )
    parser.add_argument(
        "--novelty-window-days",
        type=int,
        help="Override settings.nlp.novelty_window_days.",
    )
    parser.add_argument(
        "--skip-bigquery",
        action="store_true",
        help="Write local CSV but do not load raw.news_sentiment_raw.",
    )
    parser.add_argument(
        "--write-disposition",
        default="merge",
        choices=["merge", "append", "truncate"],
        help="BigQuery write mode. Default: merge on article_id + sentiment_model.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level.",
    )
    return parser.parse_args()


def load_articles(args: argparse.Namespace) -> pd.DataFrame:
    config = load_project()
    if args.input_news_csv:
        return read_articles_from_csv(args.input_news_csv)

    return read_table_to_dataframe(
        config=config,
        table_key="news_raw",
        columns=["article_id", "title", "clean_text", "published_at"],
    )


def load_sentiment_pipeline(model_name: str) -> Any:
    try:
        from transformers import pipeline
    except ImportError as error:
        raise RuntimeError(
            "transformers is required for FinBERT sentiment. "
            "Install dependencies with `make install`."
        ) from error
    return pipeline("sentiment-analysis", model=model_name, top_k=None)


def _coerce_finbert_score_items(scores: Any) -> list[dict[str, Any]]:
    if isinstance(scores, dict):
        return [scores]

    if isinstance(scores, str):
        return [{"label": scores, "score": 1.0}]

    if not isinstance(scores, list):
        return []

    if len(scores) == 1 and isinstance(scores[0], list):
        return _coerce_finbert_score_items(scores[0])

    items = []
    for score in scores:
        if isinstance(score, dict):
            items.append(score)
        elif isinstance(score, str):
            items.append({"label": score, "score": 1.0})
    return items


def _fill_missing_probabilities(probabilities: dict[str, float]) -> dict[str, float]:
    present_labels = [label for label, value in probabilities.items() if value > 0]
    total = sum(probabilities.values())

    if len(present_labels) == 1 and total < 1.0:
        label = present_labels[0]
        residual = 1.0 - total
        if label in {"positive", "negative"}:
            probabilities["neutral"] += residual
        else:
            probabilities["positive"] += residual / 2
            probabilities["negative"] += residual / 2
        total = sum(probabilities.values())

    if total > 0:
        probabilities = {
            label: max(0.0, min(1.0, value / total))
            for label, value in probabilities.items()
        }

    return probabilities


def normalize_finbert_scores(scores: Any) -> dict[str, float]:
    normalized = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
    for score in _coerce_finbert_score_items(scores):
        label = str(score.get("label", "")).lower()
        value = float(score.get("score", 0.0))
        if "positive" in label:
            normalized["positive"] = value
        elif "negative" in label:
            normalized["negative"] = value
        elif "neutral" in label:
            normalized["neutral"] = value
    return _fill_missing_probabilities(normalized)


def mock_sentiment_scores(text: str) -> dict[str, float]:
    lowered = text.lower()
    positive_terms = ["rise", "rises", "higher", "gain", "bullish", "strong"]
    negative_terms = ["fall", "falls", "lower", "drop", "bearish", "weak"]
    positive_hits = sum(term in lowered for term in positive_terms)
    negative_hits = sum(term in lowered for term in negative_terms)

    if positive_hits > negative_hits:
        return {"positive": 0.70, "neutral": 0.20, "negative": 0.10}
    if negative_hits > positive_hits:
        return {"positive": 0.10, "neutral": 0.20, "negative": 0.70}
    return {"positive": 0.20, "neutral": 0.60, "negative": 0.20}


def tokenize(text: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_PATTERN.finditer(text)}


def jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / len(left.union(right))


def compute_novelty_scores(
    articles: pd.DataFrame,
    window_days: int,
) -> dict[str, float]:
    if articles.empty:
        return {}

    ordered = articles.copy()
    ordered["published_at"] = pd.to_datetime(
        ordered.get("published_at"), utc=True, errors="coerce"
    )
    ordered["published_at"] = ordered["published_at"].fillna(pd.Timestamp.now(tz=UTC))
    ordered["_text"] = ordered.apply(build_article_text, axis=1)
    ordered["_tokens"] = ordered["_text"].apply(tokenize)
    ordered = ordered.sort_values("published_at")

    previous_rows: list[tuple[pd.Timestamp, set[str]]] = []
    scores = {}
    for _, row in ordered.iterrows():
        published_at = row["published_at"]
        tokens = row["_tokens"]
        cutoff = published_at - timedelta(days=window_days)
        previous_rows = [
            (date, previous_tokens)
            for date, previous_tokens in previous_rows
            if date >= cutoff
        ]
        max_similarity = max(
            (
                jaccard_similarity(tokens, previous_tokens)
                for _, previous_tokens in previous_rows
            ),
            default=0.0,
        )
        scores[row["article_id"]] = max(0.0, min(1.0, 1.0 - max_similarity))
        previous_rows.append((published_at, tokens))

    return scores


def compute_sentiment_dataframe(
    articles: pd.DataFrame,
    model_name: str,
    novelty_window_days: int,
    model: Any | None = None,
    mock_sentiment: bool = False,
) -> pd.DataFrame:
    if articles.empty:
        return pd.DataFrame(columns=[field[0] for field in SENTIMENT_SCHEMA])

    working = articles.drop_duplicates(subset=["article_id"]).copy()
    texts = working.apply(build_article_text, axis=1).tolist()
    novelty_scores = compute_novelty_scores(working, novelty_window_days)

    if mock_sentiment:
        probabilities = [mock_sentiment_scores(text) for text in texts]
        model_version = f"{model_name}:mock"
    else:
        model = model or load_sentiment_pipeline(model_name)
        raw_scores = model(texts, truncation=True)
        probabilities = [normalize_finbert_scores(scores) for scores in raw_scores]
        model_version = model_name

    calculated_at = datetime.now(UTC)
    rows = []
    for article_id, scores in zip(working["article_id"], probabilities, strict=False):
        positive = scores["positive"]
        neutral = scores["neutral"]
        negative = scores["negative"]
        rows.append(
            {
                "article_id": article_id,
                "positive_probability": positive,
                "neutral_probability": neutral,
                "negative_probability": negative,
                "sentiment_score": positive - negative,
                "novelty_score": novelty_scores.get(article_id, 1.0),
                "sentiment_model": model_name,
                "sentiment_model_version": model_version,
                "calculated_at": calculated_at,
            }
        )

    return pd.DataFrame(rows)


def write_outputs(
    sentiment: pd.DataFrame,
    output_dir: Path,
    run_date: datetime | None = None,
) -> Path:
    suffix = (run_date or datetime.now(UTC)).strftime(DATE_FORMAT)
    output_path = output_dir / f"news_sentiment_{suffix}.csv"
    sentiment.to_csv(output_path, index=False, encoding="utf-8")
    return output_path


def run_sentiment(args: argparse.Namespace) -> SentimentResult:
    config = load_project()
    model_name = args.model_name or config.settings["nlp"]["sentiment_model"]
    novelty_window_days = (
        args.novelty_window_days
        if args.novelty_window_days is not None
        else int(config.settings["nlp"]["novelty_window_days"])
    )
    output_dir = resolve_output_dir(config, args.output_dir)
    articles = load_articles(args)
    sentiment = compute_sentiment_dataframe(
        articles=articles,
        model_name=model_name,
        novelty_window_days=novelty_window_days,
        mock_sentiment=args.mock_sentiment,
    )
    output_path = write_outputs(sentiment, output_dir)
    result = SentimentResult(
        output_path=output_path,
        rows=len(sentiment),
        model_name=model_name,
    )

    if not sentiment.empty and not args.skip_bigquery:
        table_id, loaded_rows = load_dataframe_to_bigquery(
            dataframe=sentiment,
            config=config,
            table_key="news_sentiment_raw",
            schema_fields=SENTIMENT_SCHEMA,
            unique_keys=["article_id", "sentiment_model"],
            write_disposition=args.write_disposition,
            partition_field="calculated_at",
            clustering_fields=["sentiment_model"],
        )
        result = SentimentResult(
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
    run_sentiment(args)


if __name__ == "__main__":
    main()
