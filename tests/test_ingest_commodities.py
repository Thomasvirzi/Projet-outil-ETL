from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd

from scripts.extract_load.config import load_project_config
from scripts.extract_load.ingest_commodities import (
    BOOTSTRAP_SOURCE,
    build_commodities_metadata,
    clean_market_data,
    download_yfinance_data,
    ensure_symbol_multiindex,
    find_latest_market_data_snapshot,
    get_default_yfinance_end_date,
    get_market_data_columns,
    get_market_data_table_id,
    generate_bootstrap_market_data,
    load_latest_market_data_snapshot,
    merge_market_data_to_bigquery,
    next_daily_start_date,
    normalize_yfinance_output,
    prepare_bigquery_dataframe,
    select_commodities,
    write_outputs,
)


def sample_commodities() -> list[dict[str, object]]:
    return [
        {
            "commodity_id": "GOLD",
            "symbol": "GC=F",
            "name": "Gold Futures",
            "label_fr": "Or",
            "category": "precious_metals",
            "priority": "A",
            "currency": "USD",
            "source": "yahoo_finance",
            "rss_query": '"gold price"',
            "enabled": True,
        },
        {
            "commodity_id": "WTI",
            "symbol": "CL=F",
            "name": "Crude Oil WTI Futures",
            "label_fr": "Pétrole WTI",
            "category": "energy",
            "priority": "A",
            "currency": "USD",
            "source": "yahoo_finance",
            "rss_query": '"WTI crude oil"',
            "enabled": True,
        },
    ]


def test_select_commodities_filters_enabled_and_priority() -> None:
    config = load_project_config()

    commodities = select_commodities(config, priorities=["A"])

    assert commodities
    assert all(commodity["enabled"] for commodity in commodities)
    assert all(commodity["priority"] == "A" for commodity in commodities)


def test_normalize_and_clean_yfinance_multiindex() -> None:
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    columns = pd.MultiIndex.from_product(
        [
            ["Open", "High", "Low", "Close", "Adj Close", "Volume"],
            ["GC=F", "CL=F"],
        ]
    )
    raw_data = pd.DataFrame(
        [
            [2072.7, 72.1, 2088.1, 73.0, 2065.2, 71.5, 2078.4, 72.8, 2078.4, 72.8, 145321, 200000],
            [2078.4, 72.8, 2082.9, 74.0, 2048.0, 72.0, 2055.7, 73.5, 2055.7, 73.5, 151884, 210000],
        ],
        index=dates,
        columns=columns,
    )

    normalized, errors = normalize_yfinance_output(raw_data, sample_commodities())
    cleaned = clean_market_data(normalized)

    assert errors.empty
    assert len(cleaned) == 4
    assert set(cleaned["symbol"]) == {"GC=F", "CL=F"}
    assert "adjusted_close" in cleaned.columns
    assert "ingested_at" in cleaned.columns
    assert cleaned[["symbol", "date"]].duplicated().sum() == 0


def test_build_metadata_adds_rss_url() -> None:
    metadata = build_commodities_metadata(sample_commodities())

    assert set(metadata["commodity_id"]) == {"GOLD", "WTI"}
    assert metadata["rss_url"].notna().all()
    assert metadata["rss_url"].str.startswith("https://news.google.com/rss/search").all()


def test_write_outputs_creates_csv_files(tmp_path) -> None:
    prices = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2024-01-02"),
                "commodity_id": "GOLD",
                "commodity_name": "Gold Futures",
                "symbol": "GC=F",
                "close": 2078.4,
                "source": "yahoo_finance",
                "ingested_at": "2026-06-26T08:00:00+00:00",
            }
        ]
    )
    metadata = build_commodities_metadata(sample_commodities())
    errors = pd.DataFrame()

    result = write_outputs(
        prices=prices,
        metadata=metadata,
        errors=errors,
        output_dir=tmp_path,
        run_date=datetime(2026, 6, 26, tzinfo=UTC),
    )

    assert result.output_path.exists()
    assert result.metadata_path.exists()
    assert result.errors_path is None
    assert result.rows == 1


def test_load_latest_market_data_snapshot_uses_last_valid_csv(tmp_path) -> None:
    older = tmp_path / "market_data_20240102.csv"
    latest = tmp_path / "market_data_20240103.csv"
    older.write_text("symbol,date,close\nGC=F,2024-01-02,100\n", encoding="utf-8")
    latest.write_text("symbol,date,close\nGC=F,2024-01-03,101\n", encoding="utf-8")
    (tmp_path / "market_data_errors_20240104.csv").write_text(
        "symbol,error\nGC=F,error\n",
        encoding="utf-8",
    )

    snapshot = find_latest_market_data_snapshot(tmp_path)
    dataframe = load_latest_market_data_snapshot(tmp_path)

    assert snapshot == latest
    assert dataframe["date"].iloc[0] == "2024-01-03"


def test_latest_market_data_snapshot_skips_empty_csv(tmp_path) -> None:
    empty_latest = tmp_path / "market_data_20240104.csv"
    valid_older = tmp_path / "market_data_20240103.csv"
    valid_older.write_text("symbol,date,close\nGC=F,2024-01-03,101\n", encoding="utf-8")
    empty_latest.write_text("symbol,date,close\n", encoding="utf-8")

    snapshot = find_latest_market_data_snapshot(tmp_path)

    assert snapshot == valid_older


def test_ensure_symbol_multiindex_wraps_single_symbol_frame() -> None:
    frame = pd.DataFrame({"Close": [100.0]}, index=pd.to_datetime(["2024-01-02"]))

    wrapped = ensure_symbol_multiindex(frame, ["GC=F"])

    assert isinstance(wrapped.columns, pd.MultiIndex)
    assert ("Close", "GC=F") in wrapped.columns


def test_generate_bootstrap_market_data_is_clean_and_marked_as_bootstrap() -> None:
    bootstrap = generate_bootstrap_market_data(
        commodities=sample_commodities(),
        start_date="2024-01-01",
        end_date="2024-02-01",
    )
    cleaned = clean_market_data(bootstrap)

    assert not cleaned.empty
    assert set(cleaned["symbol"]) == {"GC=F", "CL=F"}
    assert cleaned["source"].eq(BOOTSTRAP_SOURCE).all()
    assert cleaned["close"].gt(0).all()
    assert (cleaned["high"] >= cleaned[["open", "close"]].max(axis=1)).all()
    assert (cleaned["low"] <= cleaned[["open", "close"]].min(axis=1)).all()


def test_download_yfinance_data_uses_sequential_batches(monkeypatch) -> None:
    calls = []

    def fake_download(symbols, **kwargs):
        calls.append((symbols, kwargs))
        return pd.DataFrame(
            {"Close": [100.0]},
            index=pd.to_datetime(["2024-01-02"]),
        )

    monkeypatch.setattr("scripts.extract_load.ingest_commodities.yf.download", fake_download)
    monkeypatch.setattr("scripts.extract_load.ingest_commodities.time.sleep", lambda seconds: None)

    data = download_yfinance_data(
        symbols=["GC=F", "CL=F"],
        start_date="2024-01-01",
        end_date="2024-01-03",
        interval="1d",
        batch_size=1,
        request_delay_seconds=0.1,
    )

    assert [call[0] for call in calls] == ["GC=F", "CL=F"]
    assert all(call[1]["threads"] is False for call in calls)
    assert isinstance(data.columns, pd.MultiIndex)
    assert ("Close", "GC=F") in data.columns
    assert ("Close", "CL=F") in data.columns


def test_prepare_bigquery_dataframe_matches_schema() -> None:
    prices = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2024-01-02"),
                "commodity_id": "GOLD",
                "commodity_name": "Gold Futures",
                "symbol": "GC=F",
                "close": 2078.4,
                "source": "yahoo_finance",
                "ingested_at": "2026-06-26T08:00:00+00:00",
            }
        ]
    )

    dataframe = prepare_bigquery_dataframe(prices)
    schema_columns = get_market_data_columns()

    assert dataframe.columns.tolist() == schema_columns
    assert str(dataframe["date"].iloc[0]) == "2024-01-02"
    assert dataframe["symbol"].iloc[0] == "GC=F"


def test_get_market_data_table_id(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    config = load_project_config()

    assert get_market_data_table_id(config) == "test-project.raw.market_data_raw"


def test_default_yfinance_end_date_is_today_for_j_minus_one_load() -> None:
    now = datetime(2026, 6, 29, 10, 30, tzinfo=UTC)

    assert get_default_yfinance_end_date(now) == "2026-06-29"


def test_next_daily_start_date_uses_day_after_latest_loaded_date() -> None:
    assert next_daily_start_date("2024-01-03", "2020-01-01") == "2024-01-04"
    assert next_daily_start_date(None, "2020-01-01") == "2020-01-01"


def test_market_merge_uses_symbol_date_unique_key(monkeypatch) -> None:
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
        "scripts.extract_load.ingest_commodities.import_bigquery_module",
        lambda: FakeBigQuery,
    )

    client = FakeClient()
    dataframe = pd.DataFrame(
        [{"symbol": "GC=F", "date": pd.Timestamp("2024-01-02").date(), "close": 1.0}]
    )
    schema = [SimpleNamespace(name=name) for name in ["symbol", "date", "close"]]

    table_id, rows = merge_market_data_to_bigquery(
        client=client,
        dataframe=dataframe,
        table_id="test-project.raw.market_data_raw",
        schema=schema,
        location="EU",
    )

    assert table_id == "test-project.raw.market_data_raw"
    assert rows == 1
    assert "MERGE `test-project.raw.market_data_raw`" in client.sql
    assert "target.symbol = source.symbol" in client.sql
    assert "target.date = source.date" in client.sql
    assert client.deleted_table.startswith("test-project.raw._tmp_market_data_raw_")
