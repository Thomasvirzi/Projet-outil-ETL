from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts.extract_load.config import load_project_config
from scripts.extract_load.ingest_benchmarks import (
    build_benchmark_dataset,
    build_index_config,
    build_selected_assets,
    clean_benchmark_dataset,
    find_latest_market_data_snapshot,
    get_default_yfinance_end_date,
    get_benchmark_columns,
    get_benchmarks_table_id,
    load_price_panel_from_market_csv,
    merge_benchmarks_to_bigquery,
    next_daily_start_date,
    resolve_market_data_fallback_path,
    select_benchmark_commodities,
    validate_benchmark_coverage,
    write_outputs,
)


def sample_commodities() -> list[dict[str, object]]:
    return [
        {
            "commodity_id": "GOLD",
            "symbol": "GC=F",
            "name": "Gold Futures",
            "category": "precious_metals",
            "priority": "A",
            "enabled": True,
        },
        {
            "commodity_id": "WTI",
            "symbol": "CL=F",
            "name": "Crude Oil WTI Futures",
            "category": "energy",
            "priority": "A",
            "enabled": True,
        },
    ]


def sample_price_panel() -> pd.DataFrame:
    dates = pd.to_datetime(
        ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
        utc=True,
    )
    return pd.DataFrame(
        {
            "GOLD": [100.0, 101.0, 102.0, 103.0],
            "WTI": [50.0, 49.0, 51.0, 52.0],
        },
        index=dates,
    )


def test_select_benchmark_commodities_defaults_to_enabled_a_b() -> None:
    config = load_project_config()

    commodities = select_benchmark_commodities(config)

    assert len(commodities) >= 2
    assert all(commodity["enabled"] for commodity in commodities)
    assert {commodity["priority"] for commodity in commodities}.issubset({"A", "B"})


def test_build_benchmark_dataset_contains_buy_hold_and_synthetic() -> None:
    config = load_project_config()
    selected_assets = build_selected_assets(sample_commodities())
    index_config = build_index_config(config)
    aligned_prices = sample_price_panel()

    benchmarks, metadata = build_benchmark_dataset(
        aligned_prices=aligned_prices,
        selected_assets=selected_assets,
        config=config,
    )
    cleaned = clean_benchmark_dataset(benchmarks)

    assert not cleaned.empty
    assert set(cleaned["benchmark_type"]) == {"buy_and_hold", "synthetic_index"}
    assert cleaned["benchmark_id"].nunique() == 3
    assert cleaned.columns.tolist() == get_benchmark_columns()
    assert metadata["benchmark_type"].isin(["buy_and_hold", "synthetic_index"]).all()
    assert index_config.base_value == 100


def test_get_benchmarks_table_id(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    config = load_project_config()

    assert get_benchmarks_table_id(config) == "test-project.raw.benchmarks_raw"


def test_write_benchmark_outputs(tmp_path) -> None:
    config = load_project_config()
    selected_assets = build_selected_assets(sample_commodities())
    benchmarks, metadata = build_benchmark_dataset(
        aligned_prices=sample_price_panel(),
        selected_assets=selected_assets,
        config=config,
    )
    cleaned = clean_benchmark_dataset(benchmarks)

    result = write_outputs(
        benchmarks=cleaned,
        metadata=metadata,
        output_dir=tmp_path,
        run_date=datetime(2026, 6, 29, tzinfo=UTC),
    )

    assert result.output_path.exists()
    assert result.metadata_path.exists()
    assert result.rows == len(cleaned)


def test_load_price_panel_from_market_csv_preserves_source(tmp_path) -> None:
    market_csv = tmp_path / "market_data_20240103.csv"
    market_csv.write_text(
        "date,commodity_id,symbol,close,source\n"
        "2024-01-02,GOLD,GC=F,100,local_bootstrap\n"
        "2024-01-02,WTI,CL=F,50,local_bootstrap\n",
        encoding="utf-8",
    )

    panel = load_price_panel_from_market_csv(
        csv_path=market_csv,
        selected_assets=build_selected_assets(sample_commodities()),
        price_field="close",
    )

    assert panel.attrs["source"] == "local_bootstrap"
    assert panel.columns.tolist() == ["GOLD", "WTI"]


def test_latest_market_data_snapshot_skips_empty_csv(tmp_path) -> None:
    valid_older = tmp_path / "market_data_20240103.csv"
    empty_latest = tmp_path / "market_data_20240104.csv"
    valid_older.write_text("date,commodity_id,close\n2024-01-03,GOLD,101\n", encoding="utf-8")
    empty_latest.write_text("date,commodity_id,close\n", encoding="utf-8")

    assert find_latest_market_data_snapshot(tmp_path) == valid_older


def test_resolve_market_data_fallback_path_uses_settings_path(monkeypatch, tmp_path) -> None:
    market_dir = tmp_path / "market_data"
    market_dir.mkdir()
    market_csv = market_dir / "market_data_20240103.csv"
    market_csv.write_text("date,commodity_id,close\n2024-01-03,GOLD,101\n", encoding="utf-8")
    config = load_project_config()
    config.settings["paths"]["market_data_raw"] = str(market_dir)

    assert resolve_market_data_fallback_path(config) == market_csv


def test_benchmark_default_end_date_and_incremental_start() -> None:
    now = datetime(2026, 6, 29, 10, 30, tzinfo=UTC)

    assert get_default_yfinance_end_date(now) == "2026-06-29"
    assert next_daily_start_date("2024-01-03", "2020-01-01") == "2024-01-04"
    assert next_daily_start_date(None, "2020-01-01") == "2020-01-01"


def test_validate_benchmark_coverage_rejects_sparse_component() -> None:
    selected_assets = build_selected_assets(sample_commodities())
    sparse_panel = sample_price_panel()
    sparse_panel["WTI"] = [50.0, None, None, None]

    with pytest.raises(ValueError, match="Insufficient benchmark price coverage"):
        validate_benchmark_coverage(
            aligned_prices=sparse_panel,
            selected_assets=selected_assets,
            min_coverage_ratio=0.80,
        )


def test_benchmark_merge_uses_date_benchmark_component_unique_key(monkeypatch) -> None:
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
        "scripts.extract_load.ingest_benchmarks.import_bigquery_module",
        lambda: FakeBigQuery,
    )

    client = FakeClient()
    dataframe = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2024-01-02").date(),
                "benchmark_id": "buy_hold_gold",
                "component_id": "GOLD",
                "benchmark_level": 100.0,
            }
        ]
    )
    schema = [
        SimpleNamespace(name=name)
        for name in ["date", "benchmark_id", "component_id", "benchmark_level"]
    ]

    table_id, rows = merge_benchmarks_to_bigquery(
        client=client,
        dataframe=dataframe,
        table_id="test-project.raw.benchmarks_raw",
        schema=schema,
        location="EU",
    )

    assert table_id == "test-project.raw.benchmarks_raw"
    assert rows == 1
    assert "MERGE `test-project.raw.benchmarks_raw`" in client.sql
    assert "target.date = source.date" in client.sql
    assert "target.benchmark_id = source.benchmark_id" in client.sql
    assert "COALESCE(target.component_id, '')" in client.sql
    assert client.deleted_table.startswith("test-project.raw._tmp_benchmarks_raw_")
