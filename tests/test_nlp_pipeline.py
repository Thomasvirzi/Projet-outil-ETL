from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts.nlp.common import (
    cosine_similarity,
    embedding_from_json,
    embedding_to_json,
    mock_embedding,
)
from scripts.nlp.compute_relevance import (
    build_commodity_descriptions,
    compute_relevance_dataframe,
    encode_commodity_descriptions,
)
from scripts.nlp.compute_sentiment import (
    compute_novelty_scores,
    compute_sentiment_dataframe,
    normalize_finbert_scores,
)
from scripts.nlp.create_embeddings import (
    create_embedding_dataframe,
    filter_pending_articles,
)
from scripts.extract_load.config import load_project_config


def sample_articles() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "article_id": "a1",
                "title": "Gold rises on weaker dollar",
                "clean_text": "Gold prices moved higher as the dollar weakened.",
                "published_at": "2026-06-29T08:00:00Z",
            },
            {
                "article_id": "a2",
                "title": "Oil falls on demand worries",
                "clean_text": "Oil prices moved lower on weak demand expectations.",
                "published_at": "2026-06-29T09:00:00Z",
            },
            {
                "article_id": "a3",
                "title": "Gold rises on weaker dollar again",
                "clean_text": "Gold prices moved higher as the dollar weakened again.",
                "published_at": "2026-06-30T08:00:00Z",
            },
        ]
    )


def test_embedding_json_roundtrip_and_cosine_similarity() -> None:
    vector = mock_embedding("gold prices rise", dimension=4)
    serialized = embedding_to_json(vector)
    restored = embedding_from_json(serialized)

    assert len(restored) == 4
    assert cosine_similarity(restored, restored) == 1.0


def test_create_embeddings_skips_existing_article_model_pairs() -> None:
    articles = sample_articles()
    pending = filter_pending_articles(
        articles=articles,
        existing_keys={("a1", "sentence-transformers/all-MiniLM-L6-v2")},
        model_name="sentence-transformers/all-MiniLM-L6-v2",
    )
    embeddings = create_embedding_dataframe(
        articles=pending,
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        mock_embeddings=True,
    )

    assert pending["article_id"].tolist() == ["a2", "a3"]
    assert embeddings["article_id"].tolist() == ["a2", "a3"]
    assert embeddings["embedding_dimension"].eq(8).all()
    assert embeddings["embedding_model_version"].str.endswith(":mock").all()


def test_build_commodity_descriptions_from_config() -> None:
    config = load_project_config()

    descriptions = build_commodity_descriptions(config)

    assert not descriptions.empty
    assert {"commodity_id", "commodity_symbol", "commodity_description"}.issubset(
        descriptions.columns
    )
    assert descriptions["commodity_description"].str.len().gt(0).all()


def test_compute_relevance_allows_multiple_commodity_matches() -> None:
    article_embeddings = pd.DataFrame(
        [
            {
                "article_id": "a1",
                "embedding": embedding_to_json([1.0, 0.0, 0.0]),
                "embedding_model": "mock-model",
            }
        ]
    )
    commodity_embeddings = pd.DataFrame(
        [
            {
                "commodity_id": "GOLD",
                "commodity_symbol": "GC=F",
                "commodity_name": "Gold Futures",
                "commodity_description": "gold precious metal",
                "embedding": embedding_to_json([1.0, 0.0, 0.0]),
            },
            {
                "commodity_id": "SILVER",
                "commodity_symbol": "SI=F",
                "commodity_name": "Silver Futures",
                "commodity_description": "silver precious metal",
                "embedding": embedding_to_json([0.9, 0.1, 0.0]),
            },
        ]
    )

    relevance = compute_relevance_dataframe(
        article_embeddings=article_embeddings,
        commodity_embeddings=commodity_embeddings,
        threshold=0.75,
    )

    assert len(relevance) == 2
    assert relevance["is_relevant"].all()
    assert set(relevance["commodity_id"]) == {"GOLD", "SILVER"}


def test_encode_commodity_descriptions_with_mock_embeddings() -> None:
    commodities = pd.DataFrame(
        [
            {
                "commodity_id": "GOLD",
                "commodity_symbol": "GC=F",
                "commodity_name": "Gold Futures",
                "commodity_description": "gold precious metal",
            }
        ]
    )

    encoded = encode_commodity_descriptions(
        commodities=commodities,
        model_name="mock-model",
        mock_embeddings=True,
    )

    assert "embedding" in encoded.columns
    assert len(embedding_from_json(encoded["embedding"].iloc[0])) == 8


def test_normalize_finbert_scores_and_sentiment_formula() -> None:
    scores = normalize_finbert_scores(
        [
            {"label": "positive", "score": 0.7},
            {"label": "neutral", "score": 0.2},
            {"label": "negative", "score": 0.1},
        ]
    )

    assert scores == {"positive": 0.7, "neutral": 0.2, "negative": 0.1}


def test_normalize_finbert_scores_accepts_single_top_label_dict() -> None:
    scores = normalize_finbert_scores({"label": "positive", "score": 0.8})

    assert scores == pytest.approx({"positive": 0.8, "neutral": 0.2, "negative": 0.0})


def test_normalize_finbert_scores_accepts_nested_scores() -> None:
    scores = normalize_finbert_scores(
        [[
            {"label": "neutral", "score": 0.6},
            {"label": "positive", "score": 0.3},
            {"label": "negative", "score": 0.1},
        ]]
    )

    assert scores == {"positive": 0.3, "neutral": 0.6, "negative": 0.1}


def test_normalize_finbert_scores_accepts_label_string() -> None:
    scores = normalize_finbert_scores("negative")

    assert scores == {"positive": 0.0, "neutral": 0.0, "negative": 1.0}


def test_compute_sentiment_dataframe_adds_probabilities_and_novelty() -> None:
    sentiment = compute_sentiment_dataframe(
        articles=sample_articles(),
        model_name="ProsusAI/finbert",
        novelty_window_days=20,
        mock_sentiment=True,
    )

    assert len(sentiment) == 3
    assert sentiment.loc[sentiment["article_id"] == "a1", "sentiment_score"].iloc[0] > 0
    assert sentiment.loc[sentiment["article_id"] == "a2", "sentiment_score"].iloc[0] < 0
    assert sentiment["novelty_score"].between(0, 1).all()


def test_compute_novelty_scores_reduces_near_duplicate_articles() -> None:
    scores = compute_novelty_scores(sample_articles(), window_days=20)

    assert scores["a1"] == 1.0
    assert scores["a3"] < 1.0
