from pathlib import Path

from dashboard.services import data_loader
from dashboard.services.bigquery_client import BigQuerySettings
from scripts.orchestrate import PipelineLog
from scripts.security_audit import scan_repository


ROOT = Path(".")


def test_gitignore_excludes_local_secrets_and_credentials() -> None:
    gitignore = Path(".gitignore").read_text(encoding="utf-8")

    expected_patterns = [
        ".env",
        ".env.*",
        "!.env.example",
        "*.json",
        "credentials/",
        "secrets/",
        ".streamlit/secrets.toml",
        "*.tfstate",
        "*.tfvars",
    ]

    for pattern in expected_patterns:
        assert pattern in gitignore


def test_security_audit_detects_private_key_pattern(tmp_path: Path) -> None:
    secret_file = tmp_path / "bad.env"
    marker = "-----BEGIN " + "PRIVATE KEY-----"
    key_name = "PRIVATE" + "_KEY"
    secret_file.write_text(key_name + "='" + marker + "abcdef'\n", encoding="utf-8")

    findings = scan_repository(tmp_path)

    assert findings
    assert findings[0].path == Path("bad.env")


def test_security_audit_repository_has_no_obvious_committed_secrets() -> None:
    findings = scan_repository(ROOT)

    assert findings == []


def test_terraform_iam_avoids_project_wide_owner_or_editor_roles() -> None:
    iam = Path("infrastructure/iam.tf").read_text(encoding="utf-8")

    assert "roles/owner" not in iam
    assert 'role    = "roles/editor"' not in iam
    assert "roles/bigquery.jobUser" in iam
    assert "roles/bigquery.dataEditor" in iam


def test_terraform_bigquery_datasets_have_labels_and_safe_destroy() -> None:
    bigquery_tf = Path("infrastructure/bigquery.tf").read_text(encoding="utf-8")

    assert "labels" in bigquery_tf
    assert "delete_contents_on_destroy = false" in bigquery_tf


def test_dbt_tables_define_partitioning_and_clustering() -> None:
    expected_files = [
        "dbt_finance/models/warehouse/int_technical_indicators.sql",
        "dbt_finance/models/warehouse/int_strategy_signals.sql",
        "dbt_finance/models/warehouse/int_daily_returns.sql",
        "dbt_finance/models/marts/mart_strategy_signals.sql",
        "dbt_finance/models/marts/mart_backtest_daily.sql",
        "dbt_finance/models/marts/mart_backtest_trades.sql",
    ]

    for relative_path in expected_files:
        sql = Path(relative_path).read_text(encoding="utf-8")
        assert "partition_by" in sql
        assert "cluster_by" in sql


def test_dashboard_known_table_loader_selects_explicit_columns(monkeypatch) -> None:
    captured_queries = []

    class FakeClient:
        def table_id(self, table_name: str) -> str:
            return f"`demo.mart.{table_name}`"

        def query_dataframe(self, query: str):
            captured_queries.append(query)
            return []

    monkeypatch.setattr(data_loader, "BigQueryClient", lambda: FakeClient())

    data_loader.load_table.__wrapped__("mart_strategy_metrics", limit=10)

    assert captured_queries
    assert "select *" not in captured_queries[0].lower()
    assert "strategy_name" in captured_queries[0]
    assert "sharpe_ratio" in captured_queries[0]


def test_bigquery_settings_define_default_maximum_bytes_billed(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    monkeypatch.delenv("BIGQUERY_MAX_BYTES_BILLED", raising=False)

    settings = BigQuerySettings.from_env()

    assert settings.maximum_bytes_billed == 1_000_000_000


def test_pipeline_logs_track_duration_seconds() -> None:
    log = PipelineLog(
        run_id="run",
        task_name="task",
        start_time="2026-07-06T00:00:00+00:00",
        end_time="2026-07-06T00:00:01+00:00",
        status="success",
        duration_seconds=1.0,
    )

    assert log.duration_seconds == 1.0
