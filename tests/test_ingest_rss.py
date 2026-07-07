from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd

from scripts.extract_load.config import load_project_config
from scripts.extract_load.ingest_rss import (
    canonicalize_url,
    clean_html_text,
    clean_news_dataframe,
    fetch_and_parse_feed,
    get_news_columns,
    get_news_table_id,
    merge_news_to_bigquery,
    normalize_article_frame_for_concat,
    parse_feed_content,
    select_rss_sources,
    write_outputs,
)


def sample_source() -> dict[str, object]:
    return {
        "source_id": "investing_commodities",
        "feed_id": "investing_commodities_news",
        "name": "Investing.com - Commodities & Futures News",
        "source_name": "Investing.com Commodities",
        "url": "https://www.investing.com/rss/news_11.rss",
        "category": "commodities_news",
        "language": "en",
        "priority": 2,
        "quality": "high",
        "enabled": True,
    }


def sample_feed_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Commodity Feed</title>
        <item>
          <title>Gold rises on weaker dollar</title>
          <link>https://example.com/article?utm_source=rss&amp;id=123</link>
          <pubDate>Mon, 29 Jun 2026 08:00:00 GMT</pubDate>
          <description><![CDATA[<p>Gold <b>prices</b> moved higher.</p>]]></description>
        </item>
        <item>
          <title>Gold rises on weaker dollar</title>
          <link>https://example.com/article?id=123</link>
          <pubDate>Mon, 29 Jun 2026 08:00:00 GMT</pubDate>
          <description><![CDATA[<p>Gold prices moved higher.</p>]]></description>
        </item>
      </channel>
    </rss>
    """


def test_select_rss_sources_uses_configured_mvp_feeds() -> None:
    config = load_project_config()

    sources = select_rss_sources(config)
    source_ids = {source["source_id"] for source in sources}

    assert len(sources) >= 5
    assert "spglobal_commodity_insights" not in source_ids
    assert "investing_commodities" in source_ids
    assert "barchart_commodities" in source_ids
    assert "cme_group" in source_ids
    assert "nasdaq_commodities" in source_ids


def test_spglobal_feeds_remain_available_when_disabled_sources_are_included() -> None:
    config = load_project_config()

    sources = select_rss_sources(config, include_disabled=True)
    spglobal_sources = [
        source for source in sources if source["source_id"] == "spglobal_commodity_insights"
    ]

    assert spglobal_sources
    assert all(source["enabled"] is False for source in spglobal_sources)


def test_known_404_cme_feeds_are_disabled_by_default() -> None:
    config = load_project_config()
    enabled_sources = select_rss_sources(config)
    disabled_sources = select_rss_sources(config, include_disabled=True)
    disabled_404_feed_ids = {
        "cme_agriculture_releases",
        "cme_energy_releases",
        "cme_all_daily_videos",
    }

    assert not disabled_404_feed_ids.intersection(
        {source["feed_id"] for source in enabled_sources}
    )
    assert disabled_404_feed_ids.issubset(
        {source["feed_id"] for source in disabled_sources}
    )


def test_clean_html_and_canonicalize_url() -> None:
    cleaned = clean_html_text("<p>Gold <b>prices</b>&nbsp;rise</p>")
    plain_text = clean_html_text("https://example.com/rss.xml")
    ampersand_text = clean_html_text("S&P futures commentary")
    canonical = canonicalize_url(
        "HTTPS://Example.com/news?id=1&utm_source=rss&gclid=abc#section"
    )

    assert cleaned == "Gold prices rise"
    assert plain_text == "https://example.com/rss.xml"
    assert ampersand_text == "S&P futures commentary"
    assert canonical == "https://example.com/news?id=1"


def test_parse_feed_content_and_dedupe_exact_articles() -> None:
    fetched_at = datetime(2026, 6, 29, 9, 0, tzinfo=UTC)

    articles = parse_feed_content(
        sample_feed_xml(),
        source=sample_source(),
        fetched_at=fetched_at,
    )
    cleaned = clean_news_dataframe(articles)

    assert len(articles) == 2
    assert len(cleaned) == 1
    assert cleaned["title"].iloc[0] == "Gold rises on weaker dollar"
    assert cleaned["clean_text"].iloc[0] == "Gold prices moved higher."
    assert cleaned["canonical_url"].iloc[0] == "https://example.com/article?id=123"
    assert cleaned.columns.tolist() == get_news_columns()


def test_fetch_and_parse_feed_returns_error_without_warning_traceback(monkeypatch, caplog) -> None:
    def failing_fetch(*args, **kwargs):
        raise RuntimeError("403 Client Error: Forbidden")

    monkeypatch.setattr("scripts.extract_load.ingest_rss.fetch_feed_content", failing_fetch)

    with caplog.at_level("WARNING"):
        articles, error = fetch_and_parse_feed(sample_source())

    assert articles.empty
    assert error["error"] == "403 Client Error: Forbidden"
    assert "RSS feed failed" in caplog.text
    assert "Traceback" not in caplog.text


def test_normalize_article_frame_for_concat_avoids_mixed_missing_columns() -> None:
    with_published_at = pd.DataFrame(
        [
            {
                "article_id": "a1",
                "title": "Gold",
                "content_hash": "h1",
                "published_at": datetime(2026, 6, 29, tzinfo=UTC),
            }
        ]
    )
    without_published_at = pd.DataFrame(
        [{"article_id": "a2", "title": "Oil", "content_hash": "h2"}]
    )

    combined = pd.concat(
        [
            normalize_article_frame_for_concat(with_published_at),
            normalize_article_frame_for_concat(without_published_at),
        ],
        ignore_index=True,
    )

    assert combined.columns.tolist() == get_news_columns()
    assert len(combined) == 2


def test_get_news_table_id(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    config = load_project_config()

    assert get_news_table_id(config) == "test-project.raw.news_raw"


def test_write_outputs_creates_news_and_errors_files(tmp_path) -> None:
    articles = clean_news_dataframe(
        parse_feed_content(
            sample_feed_xml(),
            source=sample_source(),
            fetched_at=datetime(2026, 6, 29, 9, 0, tzinfo=UTC),
        )
    )
    errors = pd.DataFrame(
        [
            {
                "source_id": "bad_source",
                "feed_id": "bad_feed",
                "error": "boom",
            }
        ]
    )

    result = write_outputs(
        articles=articles,
        errors=errors,
        output_dir=tmp_path,
        run_date=datetime(2026, 6, 29, tzinfo=UTC),
    )

    assert result.output_path.exists()
    assert result.errors_path.exists()
    assert result.rows == len(articles)


def test_news_merge_uses_article_id_unique_key(monkeypatch) -> None:
    class FakeJob:
        def result(self):
            return []

    class FakeClient:
        def __init__(self):
            self.sql = None
            self.deleted_table = None

        def load_table_from_dataframe(self, *args, **kwargs):
            return FakeJob()

        def query(self, sql, **kwargs):
            self.sql = sql
            return FakeJob()

        def delete_table(self, table_id, not_found_ok=False):
            self.deleted_table = table_id

    class FakeWriteDisposition:
        WRITE_TRUNCATE = "WRITE_TRUNCATE"

    class FakeBigQuery:
        WriteDisposition = FakeWriteDisposition

        class LoadJobConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    monkeypatch.setattr(
        "scripts.extract_load.ingest_rss.import_bigquery_module",
        lambda: FakeBigQuery,
    )

    client = FakeClient()
    dataframe = pd.DataFrame(
        [{"article_id": "abc", "title": "Gold", "content_hash": "def"}]
    )
    schema = [
        SimpleNamespace(name=name)
        for name in ["article_id", "title", "content_hash"]
    ]

    table_id, rows = merge_news_to_bigquery(
        client=client,
        dataframe=dataframe,
        table_id="test-project.raw.news_raw",
        schema=schema,
        location="EU",
    )

    assert table_id == "test-project.raw.news_raw"
    assert rows == 1
    assert "MERGE `test-project.raw.news_raw`" in client.sql
    assert "target.article_id = source.article_id" in client.sql
    assert client.deleted_table.startswith("test-project.raw._tmp_news_raw_")
