from pathlib import Path

from scripts.orchestrate import (
    FAILED,
    SKIPPED,
    SUCCESS,
    CommandResult,
    TaskSpec,
    default_tasks,
    run_pipeline,
    run_subprocess,
    run_task,
    select_tasks,
)


def test_default_tasks_follow_expected_pipeline_order() -> None:
    assert [task.name for task in default_tasks()] == [
        "ingest_market",
        "ingest_benchmarks",
        "ingest_rss",
        "create_embeddings",
        "compute_sentiment",
        "compute_relevance",
        "compute_news_indicators",
        "ensure_raw_tables",
        "dbt_run",
        "dbt_test",
        "update_backtests",
    ]


def test_select_tasks_filters_by_group() -> None:
    tasks = default_tasks()

    assert {task.group for task in select_tasks(tasks, "ingest")} == {"ingest"}
    assert len(select_tasks(tasks, "all")) == len(tasks)


def test_market_ingestion_uses_local_fallback_by_default() -> None:
    market_task = default_tasks()[0]

    assert market_task.name == "ingest_market"
    assert "--use-local-fallback" in market_task.command
    assert "--bootstrap-if-empty" in market_task.command


def test_benchmark_ingestion_uses_market_data_fallback_by_default() -> None:
    benchmark_task = default_tasks()[1]

    assert benchmark_task.name == "ingest_benchmarks"
    assert "--use-market-data-fallback" in benchmark_task.command
    assert "--prefer-market-data-fallback" in benchmark_task.command
    assert "--skip-global-external" in benchmark_task.command


def test_dbt_tasks_use_local_profiles_dir() -> None:
    tasks = {task.name: task for task in default_tasks()}

    assert tasks["ensure_raw_tables"].command[-1] == "scripts/extract_load/ensure_raw_tables.py"
    assert tasks["dbt_run"].command == ["dbt", "run", "--profiles-dir", "."]
    assert tasks["dbt_test"].command == ["dbt", "test", "--profiles-dir", "."]
    assert tasks["update_backtests"].command[:4] == ["dbt", "run", "--profiles-dir", "."]


def test_run_task_retries_after_failure() -> None:
    calls = {"count": 0}
    task = TaskSpec(name="flaky", command=["demo"], group="test", retries=1, retry_delay_seconds=0)

    def flaky_runner(_: TaskSpec) -> CommandResult:
        calls["count"] += 1
        if calls["count"] == 1:
            return CommandResult(returncode=1, stderr="temporary error")
        return CommandResult(returncode=0, rows_processed=3)

    log = run_task(task, run_id="run-1", command_runner=flaky_runner)

    assert calls["count"] == 2
    assert log.status == SUCCESS
    assert log.rows_processed == 3


def test_run_subprocess_streams_and_captures_output(capsys) -> None:
    task = TaskSpec(
        name="echo",
        command=["python", "-c", "print('hello from child')"],
        group="test",
    )

    result = run_subprocess(task)

    captured = capsys.readouterr()
    assert result.returncode == 0
    assert "hello from child" in result.stdout
    assert "hello from child" in captured.out


def test_run_pipeline_writes_logs_and_stops_on_failure(tmp_path: Path) -> None:
    tasks = [
        TaskSpec(name="ok", command=["ok"], group="test", retries=0),
        TaskSpec(name="fail", command=["fail"], group="test", retries=0),
        TaskSpec(name="skipped_after_fail", command=["skip"], group="test", retries=0),
    ]

    def runner(task: TaskSpec) -> CommandResult:
        return CommandResult(returncode=1, stderr="boom") if task.name == "fail" else CommandResult(returncode=0)

    _, logs, log_path = run_pipeline(tasks=tasks, command_runner=runner, log_dir=tmp_path)

    assert [log.task_name for log in logs] == ["ok", "fail", "final_status"]
    assert logs[-1].status == FAILED
    assert log_path.exists()
    assert "boom" in log_path.read_text(encoding="utf-8")


def test_run_pipeline_can_continue_after_error(tmp_path: Path) -> None:
    tasks = [
        TaskSpec(name="fail", command=["fail"], group="test", retries=0),
        TaskSpec(name="after_fail", command=["ok"], group="test", retries=0),
    ]

    def runner(task: TaskSpec) -> CommandResult:
        return CommandResult(returncode=1, stderr="boom") if task.name == "fail" else CommandResult(returncode=0)

    _, logs, _ = run_pipeline(
        tasks=tasks,
        command_runner=runner,
        continue_on_error=True,
        log_dir=tmp_path,
    )

    assert [log.task_name for log in logs] == ["fail", "after_fail", "final_status"]
    assert logs[-1].status == FAILED


def test_dry_run_marks_tasks_as_skipped(tmp_path: Path) -> None:
    tasks = [TaskSpec(name="dry", command=["demo"], group="test")]

    _, logs, _ = run_pipeline(tasks=tasks, dry_run=True, log_dir=tmp_path)

    assert logs[0].status == SKIPPED
    assert logs[-1].status == SUCCESS
