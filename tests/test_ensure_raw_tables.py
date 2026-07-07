from scripts.extract_load.ensure_raw_tables import PIPELINE_LOGS_SCHEMA, RAW_TABLE_SPECS


def test_optional_raw_table_specs_cover_dbt_missing_sources() -> None:
    expected_tables = {
        "market_data_raw",
        "benchmarks_raw",
        "news_raw",
        "news_embeddings_raw",
        "news_sentiment_raw",
        "article_commodity_relevance_raw",
        "news_features_raw",
        "pipeline_logs_raw",
    }

    assert expected_tables.issubset(RAW_TABLE_SPECS)


def test_pipeline_logs_schema_matches_orchestration_log_columns() -> None:
    columns = [column for column, _, _ in PIPELINE_LOGS_SCHEMA]

    assert columns == [
        "run_id",
        "task_name",
        "start_time",
        "end_time",
        "status",
        "duration_seconds",
        "rows_processed",
        "error_message",
    ]
