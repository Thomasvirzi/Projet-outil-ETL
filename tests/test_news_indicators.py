from datetime import UTC, datetime

import pandas as pd

from scripts.nlp.compute_news_indicators import (
    aggregate_daily_features,
    build_dense_commodity_date_grid,
    compute_news_acceleration,
    compute_news_surprise,
    compute_theme_scores,
    prepare_article_signal_dataframe,
    source_weight_from_row,
    write_outputs,
)


def sample_news() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "article_id": "a1",
                "published_at": "2026-06-27T08:00:00Z",
                "source_id": "spglobal",
                "category": "oil",
                "title": "Oil supply disruption after geopolitical sanctions",
                "summary": "Export sanctions create supply shock fears.",
                "clean_text": "Pipeline outage and sanctions reduce oil supply.",
                "priority": 1,
                "quality": "very_high",
            },
            {
                "article_id": "a2",
                "published_at": "2026-06-29T09:00:00Z",
                "source_id": "investing",
                "category": "agriculture",
                "title": "Gold rises while crop weather concerns persist",
                "summary": "Drought and storm risks affect agriculture markets.",
                "clean_text": "Weather risk remains elevated after drought.",
                "priority": 2,
                "quality": "high",
            },
        ]
    )


def sample_relevance() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "article_id": "a1",
                "commodity_id": "GOLD",
                "commodity_symbol": "GC=F",
                "similarity_score": 0.90,
                "is_relevant": True,
            },
            {
                "article_id": "a1",
                "commodity_id": "WTI",
                "commodity_symbol": "CL=F",
                "similarity_score": 0.20,
                "is_relevant": False,
            },
            {
                "article_id": "a2",
                "commodity_id": "GOLD",
                "commodity_symbol": "GC=F",
                "similarity_score": 0.80,
                "is_relevant": True,
            },
        ]
    )


def sample_sentiment() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "article_id": "a1",
                "sentiment_score": 0.60,
                "novelty_score": 1.00,
            },
            {
                "article_id": "a2",
                "sentiment_score": -0.40,
                "novelty_score": 0.50,
            },
        ]
    )


def test_source_weight_combines_quality_and_priority() -> None:
    high = source_weight_from_row(pd.Series({"quality": "very_high", "priority": 1}))
    lower = source_weight_from_row(pd.Series({"quality": "medium_high", "priority": 5}))

    assert high > lower
    assert high == 1.44


def test_prepare_article_signal_dataframe_integrates_relevance_sentiment_freshness() -> None:
    signals = prepare_article_signal_dataframe(
        news=sample_news(),
        relevance=sample_relevance(),
        sentiment=sample_sentiment(),
    )

    assert len(signals) == 2
    assert set(signals["article_id"]) == {"a1", "a2"}
    assert signals["freshness_score"].between(0, 1).all()
    assert signals["signal_weight"].gt(0).all()
    assert "pressure_component" in signals.columns
    assert "geopolitical_risk_component" in signals.columns
    assert "supply_shock_component" in signals.columns
    assert "weather_risk_component" in signals.columns


def test_compute_theme_scores_detects_geopolitical_supply_and_weather() -> None:
    scores = compute_theme_scores(
        pd.Series(
            {
                "category": "agriculture",
                "title": "Sanctions and drought disrupt crop exports",
                "summary": "Supply shortage fears grow.",
                "clean_text": "Weather and geopolitical risks hit supply.",
            }
        )
    )

    assert scores["geopolitical_theme_score"] > 0
    assert scores["supply_theme_score"] > 0
    assert scores["weather_theme_score"] > 0


def test_aggregate_daily_features_fills_days_without_articles() -> None:
    signals = prepare_article_signal_dataframe(
        news=sample_news(),
        relevance=sample_relevance(),
        sentiment=sample_sentiment(),
    )

    features = aggregate_daily_features(
        signals=signals,
        start_date="2026-06-27",
        end_date="2026-06-29",
        surprise_window=20,
    )

    assert len(features) == 3
    assert features["commodity_id"].eq("GOLD").all()
    assert features["news_volume"].tolist() == [1, 0, 1]
    assert features.loc[features["date"] == pd.to_datetime("2026-06-28").date(), "news_pressure_score"].iloc[0] == 0
    assert features["news_surprise_20d"].notna().all()
    assert features["news_acceleration"].tolist() == [0.0, -1.0, 1.0]
    assert features["sentiment_dispersion"].notna().all()
    assert features["geopolitical_risk_score"].iloc[0] > 0
    assert features["supply_shock_score"].iloc[0] > 0
    assert features["weather_risk_score"].iloc[-1] > 0


def test_aggregate_daily_features_ignores_rows_without_valid_date() -> None:
    signals = prepare_article_signal_dataframe(
        news=sample_news(),
        relevance=sample_relevance(),
        sentiment=sample_sentiment(),
    )
    invalid_signal = signals.iloc[[0]].copy()
    invalid_signal["date"] = float("nan")
    signals = pd.concat([signals, invalid_signal], ignore_index=True)

    grid = build_dense_commodity_date_grid(signals)
    features = aggregate_daily_features(signals)

    assert grid["date"].notna().all()
    assert features["date"].notna().all()
    assert features["news_volume"].sum() == 2


def test_compute_news_surprise_uses_prior_rolling_window() -> None:
    surprise = compute_news_surprise(pd.Series([1, 1, 5]), window=2)

    assert surprise.iloc[0] == 0
    assert surprise.iloc[1] == 0
    assert surprise.iloc[2] == 0


def test_compute_news_acceleration_is_day_over_day_change() -> None:
    acceleration = compute_news_acceleration(pd.Series([1, 0, 3]))

    assert acceleration.tolist() == [0.0, -1.0, 3.0]


def test_write_outputs_creates_features_csv(tmp_path) -> None:
    signals = prepare_article_signal_dataframe(
        news=sample_news(),
        relevance=sample_relevance(),
        sentiment=sample_sentiment(),
    )
    features = aggregate_daily_features(signals)

    output_path = write_outputs(
        features=features,
        output_dir=tmp_path,
        run_date=datetime(2026, 6, 29, tzinfo=UTC),
    )

    assert output_path.exists()
    assert output_path.name == "news_features_20260629.csv"
