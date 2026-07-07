from datetime import UTC, datetime

import pandas as pd

from backtesting.engine import BacktestEngine
from backtesting.metrics import compare_backtest_results
from backtesting.models import BacktestConfig
from backtesting.strategies import BuyAndHoldStrategy, TechnicalNewsFilterStrategy
from dashboard.services.filters import filter_dataframe
from scripts.extract_load.ingest_commodities import clean_market_data
from scripts.nlp.compute_news_indicators import (
    aggregate_daily_features,
    prepare_article_signal_dataframe,
)


def test_source_to_dashboard_e2e_scenario() -> None:
    raw_prices = pd.DataFrame(
        [
            {
                "date": "2026-01-01",
                "commodity_id": "GOLD",
                "commodity_name": "Gold Futures",
                "symbol": "GC=F",
                "category": "metals",
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "adjusted_close": 100,
                "volume": 1000,
                "source": "test",
            },
            {
                "date": "2026-01-02",
                "commodity_id": "GOLD",
                "commodity_name": "Gold Futures",
                "symbol": "GC=F",
                "category": "metals",
                "open": 100,
                "high": 112,
                "low": 99,
                "close": 110,
                "adjusted_close": 110,
                "volume": 1200,
                "source": "test",
            },
            {
                "date": "2026-01-03",
                "commodity_id": "GOLD",
                "commodity_name": "Gold Futures",
                "symbol": "GC=F",
                "category": "metals",
                "open": 110,
                "high": 122,
                "low": 109,
                "close": 120,
                "adjusted_close": 120,
                "volume": 1300,
                "source": "test",
            },
        ]
    )
    prices = clean_market_data(raw_prices)

    news = pd.DataFrame(
        [
            {
                "article_id": "a1",
                "published_at": "2026-01-01T08:00:00Z",
                "source_id": "source",
                "category": "metals",
                "title": "Gold demand improves",
                "summary": "Investors buy gold.",
                "clean_text": "Gold demand improves as investors buy.",
                "priority": 1,
                "quality": "high",
            }
        ]
    )
    relevance = pd.DataFrame(
        [
            {
                "article_id": "a1",
                "commodity_id": "GOLD",
                "commodity_symbol": "GC=F",
                "similarity_score": 0.9,
                "is_relevant": True,
            }
        ]
    )
    sentiment = pd.DataFrame(
        [{"article_id": "a1", "sentiment_score": 0.4, "novelty_score": 1.0}]
    )
    article_signals = prepare_article_signal_dataframe(news, relevance, sentiment)
    news_features = aggregate_daily_features(
        article_signals,
        start_date="2026-01-01",
        end_date="2026-01-03",
    )
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    news_features["date"] = pd.to_datetime(news_features["date"]).dt.date

    strategy_input = prices.merge(
        news_features,
        left_on=["commodity_id", "symbol", "date"],
        right_on=["commodity_id", "commodity_symbol", "date"],
        how="left",
    )
    strategy_input["sma_20"] = [99, 100, 105]
    strategy_input["sma_50"] = [98, 99, 100]
    strategy_input["rsi_14"] = [55, 60, 62]
    strategy_input["stochastic_rsi_k"] = [40, 45, 50]
    strategy_input["stochastic_rsi_d"] = [45, 50, 55]
    strategy_input[["weighted_sentiment_score", "geopolitical_risk_score", "supply_shock_score"]] = (
        strategy_input[["weighted_sentiment_score", "geopolitical_risk_score", "supply_shock_score"]].fillna(0)
    )

    engine = BacktestEngine(
        BacktestConfig(
            strategy_name="e2e",
            initial_capital=10_000,
            fee_rate=0,
            slippage_rate=0,
            run_at=datetime(2026, 1, 4, tzinfo=UTC),
        )
    )
    results = engine.run_many(
        strategy_input,
        [BuyAndHoldStrategy(), TechnicalNewsFilterStrategy()],
    )
    comparison = compare_backtest_results(results)
    dashboard_view = filter_dataframe(comparison, symbol="GC=F")

    assert len(prices) == 3
    assert not news_features.empty
    assert set(comparison["strategy_name"]) == {"buy_and_hold", "technical_news_filter"}
    assert not dashboard_view.empty
