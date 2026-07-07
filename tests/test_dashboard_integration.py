import pandas as pd

from dashboard.services import data_loader


class FakeBigQueryClient:
    queries: list[str] = []

    def table_id(self, table_name: str, dataset: str | None = None) -> str:
        return f"`demo.{dataset or 'marts'}.{table_name}`"

    def query_dataframe(self, query: str) -> pd.DataFrame:
        self.queries.append(query)
        return pd.DataFrame([{"symbol": "GC=F", "strategy_name": "buy_and_hold"}])


def test_dashboard_loader_queries_mart_strategy_signals(monkeypatch) -> None:
    fake_client = FakeBigQueryClient()
    monkeypatch.setattr(data_loader, "BigQueryClient", lambda: fake_client)

    dataframe = data_loader.load_strategy_signals.__wrapped__(symbol="GC=F")

    assert not dataframe.empty
    assert "mart_strategy_signals" in fake_client.queries[-1]
    assert "symbol = 'GC=F'" in fake_client.queries[-1]


def test_dashboard_loader_queries_staging_pipeline_logs(monkeypatch) -> None:
    fake_client = FakeBigQueryClient()
    fake_client.settings = type("Settings", (), {"staging_dataset": "staging"})()
    monkeypatch.setattr(data_loader, "BigQueryClient", lambda: fake_client)

    dataframe = data_loader.load_pipeline_logs.__wrapped__()

    assert not dataframe.empty
    assert "stg_pipeline_logs" in fake_client.queries[-1]
    assert "`demo.staging.stg_pipeline_logs`" in fake_client.queries[-1]

