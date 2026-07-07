from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re

import pandas as pd

try:
    from scripts.nlp.common import (
        DATE_FORMAT,
        configure_logging,
        load_dataframe_to_bigquery,
        load_project,
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
        load_dataframe_to_bigquery,
        load_project,
        read_table_to_dataframe,
        resolve_output_dir,
    )


NEWS_FEATURES_SCHEMA = [
    ("commodity_id", "STRING", "REQUIRED"),
    ("commodity_symbol", "STRING", "NULLABLE"),
    ("date", "DATE", "REQUIRED"),
    ("news_volume", "INTEGER", "NULLABLE"),
    ("relevant_news_volume", "INTEGER", "NULLABLE"),
    ("weighted_sentiment_score", "FLOAT", "NULLABLE"),
    ("avg_relevance_score", "FLOAT", "NULLABLE"),
    ("avg_novelty_score", "FLOAT", "NULLABLE"),
    ("sentiment_dispersion", "FLOAT", "NULLABLE"),
    ("freshness_score", "FLOAT", "NULLABLE"),
    ("source_weight", "FLOAT", "NULLABLE"),
    ("news_pressure_score", "FLOAT", "NULLABLE"),
    ("news_surprise_20d", "FLOAT", "NULLABLE"),
    ("news_acceleration", "FLOAT", "NULLABLE"),
    ("geopolitical_risk_score", "FLOAT", "NULLABLE"),
    ("supply_shock_score", "FLOAT", "NULLABLE"),
    ("weather_risk_score", "FLOAT", "NULLABLE"),
    ("calculated_at", "TIMESTAMP", "NULLABLE"),
]

SOURCE_QUALITY_WEIGHTS = {
    "very_high": 1.20,
    "high": 1.00,
    "medium_high": 0.85,
    "medium": 0.70,
    "low": 0.50,
}

GEOPOLITICAL_KEYWORDS = {
    "war",
    "conflict",
    "sanction",
    "sanctions",
    "embargo",
    "tariff",
    "tariffs",
    "geopolitical",
    "opec",
    "russia",
    "ukraine",
    "middle east",
    "red sea",
    "strait",
    "attack",
    "export ban",
}

SUPPLY_SHOCK_KEYWORDS = {
    "supply",
    "shortage",
    "disruption",
    "outage",
    "strike",
    "inventory",
    "inventories",
    "stockpile",
    "production cut",
    "output cut",
    "mine",
    "harvest",
    "crop",
    "export",
    "import",
    "refinery",
    "pipeline",
}

WEATHER_KEYWORDS = {
    "weather",
    "drought",
    "flood",
    "frost",
    "freeze",
    "hurricane",
    "storm",
    "heatwave",
    "rainfall",
    "el nino",
    "la nina",
    "wildfire",
}

WORD_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9 -]{2,}")


@dataclass(frozen=True)
class NewsIndicatorsResult:
    output_path: Path
    rows: int
    bigquery_table: str | None = None
    bigquery_rows: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate NLP outputs into commodity daily news indicators."
    )
    parser.add_argument("--input-news-csv", type=Path, help="Local news CSV.")
    parser.add_argument(
        "--input-relevance-csv",
        type=Path,
        help="Local article_commodity_relevance CSV.",
    )
    parser.add_argument("--input-sentiment-csv", type=Path, help="Local sentiment CSV.")
    parser.add_argument("--output-dir", help="Output directory for news features CSV.")
    parser.add_argument(
        "--start-date",
        help="Optional YYYY-MM-DD start date for the dense commodity/date grid.",
    )
    parser.add_argument(
        "--end-date",
        help="Optional YYYY-MM-DD end date for the dense commodity/date grid.",
    )
    parser.add_argument(
        "--surprise-window",
        type=int,
        default=20,
        help="Rolling window used for news_surprise_20d.",
    )
    parser.add_argument(
        "--skip-bigquery",
        action="store_true",
        help="Write local CSV but do not load raw.news_features_raw.",
    )
    parser.add_argument(
        "--write-disposition",
        default="merge",
        choices=["merge", "append", "truncate"],
        help="BigQuery write mode. Default: merge on commodity_id + date.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level.",
    )
    return parser.parse_args()


def load_news(args: argparse.Namespace) -> pd.DataFrame:
    config = load_project()
    if args.input_news_csv:
        return pd.read_csv(args.input_news_csv)

    return read_table_to_dataframe(
        config=config,
        table_key="news_raw",
        columns=[
            "article_id",
            "published_at",
            "source_id",
            "category",
            "title",
            "clean_text",
            "summary",
            "priority",
            "quality",
        ],
    )


def load_relevance(args: argparse.Namespace) -> pd.DataFrame:
    config = load_project()
    if args.input_relevance_csv:
        return pd.read_csv(args.input_relevance_csv)

    return read_table_to_dataframe(
        config=config,
        table_key="article_commodity_relevance_raw",
        columns=[
            "article_id",
            "commodity_id",
            "commodity_symbol",
            "similarity_score",
            "is_relevant",
        ],
    )


def load_sentiment(args: argparse.Namespace) -> pd.DataFrame:
    config = load_project()
    if args.input_sentiment_csv:
        return pd.read_csv(args.input_sentiment_csv)

    return read_table_to_dataframe(
        config=config,
        table_key="news_sentiment_raw",
        columns=["article_id", "sentiment_score", "novelty_score"],
    )


def source_weight_from_row(row: pd.Series) -> float:
    quality_weight = SOURCE_QUALITY_WEIGHTS.get(str(row.get("quality", "")).lower(), 0.75)
    priority = pd.to_numeric(row.get("priority"), errors="coerce")
    if pd.isna(priority) or priority <= 0:
        priority_weight = 0.75
    else:
        priority_weight = max(0.50, 1.20 - (float(priority) - 1.0) * 0.10)

    return round(quality_weight * priority_weight, 6)


def normalize_theme_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).lower().replace("_", " ")


def build_theme_text(row: pd.Series) -> str:
    parts = [
        normalize_theme_text(row.get("category")),
        normalize_theme_text(row.get("title")),
        normalize_theme_text(row.get("summary")),
        normalize_theme_text(row.get("clean_text")),
    ]
    return " ".join(part for part in parts if part)


def keyword_score(text: str, keywords: set[str]) -> float:
    if not text:
        return 0.0

    hits = 0
    for keyword in keywords:
        if " " in keyword:
            hits += int(keyword in text)
        else:
            hits += int(bool(re.search(rf"\b{re.escape(keyword)}\b", text)))

    return min(1.0, hits / 3.0)


def compute_theme_scores(row: pd.Series) -> pd.Series:
    text = build_theme_text(row)
    category = normalize_theme_text(row.get("category"))

    geopolitical = keyword_score(text, GEOPOLITICAL_KEYWORDS)
    supply = keyword_score(text, SUPPLY_SHOCK_KEYWORDS)
    weather = keyword_score(text, WEATHER_KEYWORDS)

    if category in {"oil", "natural gas", "lng", "energy", "energy transition"}:
        supply = max(supply, 0.35)
    if category in {"agriculture", "grains", "softs"}:
        weather = max(weather, 0.35)
        supply = max(supply, 0.25)

    return pd.Series(
        {
            "geopolitical_theme_score": geopolitical,
            "supply_theme_score": supply,
            "weather_theme_score": weather,
        }
    )


def compute_freshness_score(
    published_at: pd.Series,
    dates: pd.Series,
) -> pd.Series:
    published = pd.to_datetime(published_at, utc=True, errors="coerce")
    target_dates = pd.to_datetime(dates, utc=True, errors="coerce")
    age_days = (target_dates.dt.normalize() - published.dt.normalize()).dt.days
    age_days = age_days.clip(lower=0).fillna(0)
    return 1.0 / (1.0 + age_days)


def prepare_article_signal_dataframe(
    news: pd.DataFrame,
    relevance: pd.DataFrame,
    sentiment: pd.DataFrame,
) -> pd.DataFrame:
    if news.empty or relevance.empty or sentiment.empty:
        return pd.DataFrame()

    news_work = news.copy()
    relevance_work = relevance.copy()
    sentiment_work = sentiment.copy()

    news_work["published_at"] = pd.to_datetime(
        news_work["published_at"], utc=True, errors="coerce"
    )
    news_work["date"] = news_work["published_at"].dt.date
    news_work = news_work.dropna(subset=["date"])
    if news_work.empty:
        return pd.DataFrame()
    for optional_column in ["category", "title", "summary", "clean_text"]:
        if optional_column not in news_work.columns:
            news_work[optional_column] = ""
    news_work["source_weight"] = news_work.apply(source_weight_from_row, axis=1)
    news_work = pd.concat(
        [news_work, news_work.apply(compute_theme_scores, axis=1)],
        axis=1,
    )

    relevance_work["is_relevant"] = relevance_work["is_relevant"].astype(bool)
    relevance_work["similarity_score"] = pd.to_numeric(
        relevance_work["similarity_score"], errors="coerce"
    ).fillna(0)

    sentiment_work["sentiment_score"] = pd.to_numeric(
        sentiment_work["sentiment_score"], errors="coerce"
    ).fillna(0)
    sentiment_work["novelty_score"] = pd.to_numeric(
        sentiment_work["novelty_score"], errors="coerce"
    ).fillna(1)

    signals = relevance_work.merge(
        news_work[
            [
                "article_id",
                "published_at",
                "date",
                "source_id",
                "source_weight",
                "geopolitical_theme_score",
                "supply_theme_score",
                "weather_theme_score",
            ]
        ],
        on="article_id",
        how="inner",
    ).merge(
        sentiment_work[["article_id", "sentiment_score", "novelty_score"]],
        on="article_id",
        how="inner",
    )
    signals = signals[signals["is_relevant"]].copy()
    if signals.empty:
        return signals

    signals["freshness_score"] = compute_freshness_score(
        signals["published_at"],
        pd.to_datetime(signals["date"]),
    )
    signals["signal_weight"] = (
        signals["similarity_score"]
        * signals["source_weight"]
        * signals["freshness_score"]
        * signals["novelty_score"].clip(lower=0, upper=1)
    )
    signals["weighted_sentiment_component"] = (
        signals["sentiment_score"] * signals["signal_weight"]
    )
    signals["pressure_component"] = (
        signals["sentiment_score"].abs() * signals["signal_weight"]
    )
    signals["geopolitical_risk_component"] = (
        signals["pressure_component"] * signals["geopolitical_theme_score"]
    )
    signals["supply_shock_component"] = (
        signals["pressure_component"] * signals["supply_theme_score"]
    )
    signals["weather_risk_component"] = (
        signals["pressure_component"] * signals["weather_theme_score"]
    )
    return signals


def build_dense_commodity_date_grid(
    signals: pd.DataFrame,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    if signals.empty:
        return pd.DataFrame(columns=["commodity_id", "commodity_symbol", "date"])

    signals_work = signals.copy()
    signals_work["date"] = pd.to_datetime(
        signals_work["date"], errors="coerce"
    ).dt.date
    signals_work = signals_work.dropna(subset=["date"])
    if signals_work.empty:
        return pd.DataFrame(columns=["commodity_id", "commodity_symbol", "date"])

    commodities = signals_work[["commodity_id", "commodity_symbol"]].drop_duplicates()
    start = pd.to_datetime(start_date or signals_work["date"].min()).date()
    end = pd.to_datetime(end_date or signals_work["date"].max()).date()
    dates = pd.date_range(start=start, end=end, freq="D").date

    return commodities.merge(pd.DataFrame({"date": dates}), how="cross")


def aggregate_daily_features(
    signals: pd.DataFrame,
    start_date: str | None = None,
    end_date: str | None = None,
    surprise_window: int = 20,
) -> pd.DataFrame:
    if signals.empty:
        return pd.DataFrame(columns=[field[0] for field in NEWS_FEATURES_SCHEMA])

    signals = signals.copy()
    signals["date"] = pd.to_datetime(signals["date"], errors="coerce").dt.date
    signals = signals.dropna(subset=["date"])
    if signals.empty:
        return pd.DataFrame(columns=[field[0] for field in NEWS_FEATURES_SCHEMA])

    grouped = (
        signals.groupby(["commodity_id", "commodity_symbol", "date"], dropna=False)
        .agg(
            news_volume=("article_id", "nunique"),
            relevant_news_volume=("article_id", "nunique"),
            weighted_sentiment_sum=("weighted_sentiment_component", "sum"),
            signal_weight_sum=("signal_weight", "sum"),
            avg_relevance_score=("similarity_score", "mean"),
            avg_novelty_score=("novelty_score", "mean"),
            sentiment_dispersion=("sentiment_score", "std"),
            freshness_score=("freshness_score", "mean"),
            source_weight=("source_weight", "mean"),
            news_pressure_score=("pressure_component", "sum"),
            geopolitical_risk_score=("geopolitical_risk_component", "sum"),
            supply_shock_score=("supply_shock_component", "sum"),
            weather_risk_score=("weather_risk_component", "sum"),
        )
        .reset_index()
    )
    grouped["weighted_sentiment_score"] = (
        grouped["weighted_sentiment_sum"] / grouped["signal_weight_sum"]
    ).fillna(0)
    grouped["sentiment_dispersion"] = grouped["sentiment_dispersion"].fillna(0)

    grid = build_dense_commodity_date_grid(signals, start_date, end_date)
    dense = grid.merge(
        grouped.drop(columns=["weighted_sentiment_sum", "signal_weight_sum"]),
        on=["commodity_id", "commodity_symbol", "date"],
        how="left",
    )

    fill_zero_columns = [
        "news_volume",
        "relevant_news_volume",
        "weighted_sentiment_score",
        "avg_relevance_score",
        "avg_novelty_score",
        "sentiment_dispersion",
        "freshness_score",
        "source_weight",
        "news_pressure_score",
        "geopolitical_risk_score",
        "supply_shock_score",
        "weather_risk_score",
    ]
    dense[fill_zero_columns] = dense[fill_zero_columns].fillna(0)
    dense["news_volume"] = dense["news_volume"].astype(int)
    dense["relevant_news_volume"] = dense["relevant_news_volume"].astype(int)
    dense = dense.sort_values(["commodity_id", "date"]).reset_index(drop=True)
    dense["news_surprise_20d"] = dense.groupby("commodity_id")[
        "news_volume"
    ].transform(lambda series: compute_news_surprise(series, surprise_window))
    dense["news_acceleration"] = dense.groupby("commodity_id")[
        "news_volume"
    ].transform(compute_news_acceleration)
    dense["calculated_at"] = datetime.now(UTC)
    return dense[[field[0] for field in NEWS_FEATURES_SCHEMA]]


def compute_news_surprise(series: pd.Series, window: int) -> pd.Series:
    rolling_mean = series.shift(1).rolling(window=window, min_periods=1).mean()
    rolling_std = series.shift(1).rolling(window=window, min_periods=2).std()
    surprise = (series - rolling_mean) / rolling_std.replace(0, pd.NA)
    return surprise.fillna(0)


def compute_news_acceleration(series: pd.Series) -> pd.Series:
    return series.diff().fillna(0)


def write_outputs(
    features: pd.DataFrame,
    output_dir: Path,
    run_date: datetime | None = None,
) -> Path:
    suffix = (run_date or datetime.now(UTC)).strftime(DATE_FORMAT)
    output_path = output_dir / f"news_features_{suffix}.csv"
    features.to_csv(output_path, index=False, encoding="utf-8")
    return output_path


def run_news_indicators(args: argparse.Namespace) -> NewsIndicatorsResult:
    config = load_project()
    output_dir = resolve_output_dir(config, args.output_dir)
    news = load_news(args)
    relevance = load_relevance(args)
    sentiment = load_sentiment(args)
    signals = prepare_article_signal_dataframe(news, relevance, sentiment)
    features = aggregate_daily_features(
        signals=signals,
        start_date=args.start_date,
        end_date=args.end_date,
        surprise_window=args.surprise_window,
    )
    output_path = write_outputs(features, output_dir)
    result = NewsIndicatorsResult(output_path=output_path, rows=len(features))

    if not features.empty and not args.skip_bigquery:
        loadable_features = features.copy()
        loadable_features["date"] = pd.to_datetime(loadable_features["date"]).dt.date
        table_id, loaded_rows = load_dataframe_to_bigquery(
            dataframe=loadable_features,
            config=config,
            table_key="news_features_raw",
            schema_fields=NEWS_FEATURES_SCHEMA,
            unique_keys=["commodity_id", "date"],
            write_disposition=args.write_disposition,
            partition_field="date",
            clustering_fields=["commodity_id"],
        )
        result = NewsIndicatorsResult(
            output_path=result.output_path,
            rows=result.rows,
            bigquery_table=table_id,
            bigquery_rows=loaded_rows,
        )

    return result


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)
    run_news_indicators(args)


if __name__ == "__main__":
    main()
