#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
SUCCESS = "success"
FAILED = "failed"
SKIPPED = "skipped"


@dataclass(frozen=True)
class TaskSpec:
    name: str
    command: list[str]
    group: str
    cwd: Path = PROJECT_ROOT
    retries: int = 1
    retry_delay_seconds: float = 2.0


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    rows_processed: int | None = None


@dataclass
class PipelineLog:
    run_id: str
    task_name: str
    start_time: str
    end_time: str
    status: str
    duration_seconds: float
    rows_processed: int | None = None
    error_message: str | None = None


CommandRunner = Callable[[TaskSpec], CommandResult]


def default_tasks() -> list[TaskSpec]:
    python = sys.executable
    return [
        TaskSpec(
            name="ingest_market",
            group="ingest",
            command=[
                python,
                "scripts/extract_load/ingest_commodities.py",
                "--use-local-fallback",
                "--bootstrap-if-empty",
            ],
            retries=2,
        ),
        TaskSpec(
            name="ingest_benchmarks",
            group="ingest",
            command=[
                python,
                "scripts/extract_load/ingest_benchmarks.py",
                "--use-market-data-fallback",
                "--prefer-market-data-fallback",
                "--skip-global-external",
            ],
            retries=2,
        ),
        TaskSpec(
            name="ingest_rss",
            group="ingest",
            command=[python, "scripts/extract_load/ingest_rss.py"],
            retries=2,
        ),
        TaskSpec(
            name="create_embeddings",
            group="nlp",
            command=[python, "scripts/nlp/create_embeddings.py"],
            retries=1,
        ),
        TaskSpec(
            name="compute_sentiment",
            group="nlp",
            command=[python, "scripts/nlp/compute_sentiment.py"],
            retries=1,
        ),
        TaskSpec(
            name="compute_relevance",
            group="nlp",
            command=[python, "scripts/nlp/compute_relevance.py"],
            retries=1,
        ),
        TaskSpec(
            name="compute_news_indicators",
            group="nlp",
            command=[python, "scripts/nlp/compute_news_indicators.py"],
            retries=1,
        ),
        TaskSpec(
            name="ensure_raw_tables",
            group="dbt",
            command=[python, "scripts/extract_load/ensure_raw_tables.py"],
            retries=0,
        ),
        TaskSpec(
            name="dbt_run",
            group="dbt",
            command=["dbt", "run", "--profiles-dir", "."],
            cwd=PROJECT_ROOT / "dbt_finance",
            retries=0,
        ),
        TaskSpec(
            name="dbt_test",
            group="dbt",
            command=["dbt", "test", "--profiles-dir", "."],
            cwd=PROJECT_ROOT / "dbt_finance",
            retries=0,
        ),
        TaskSpec(
            name="update_backtests",
            group="backtest",
            command=[
                "dbt",
                "run",
                "--profiles-dir",
                ".",
                "--select",
                "mart_backtest_daily",
                "mart_backtest_trades",
                "mart_strategy_metrics",
                "mart_validation_period_metrics",
                "mart_rss_filter_contribution",
            ],
            cwd=PROJECT_ROOT / "dbt_finance",
            retries=0,
        ),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the daily ELT/backtesting pipeline.")
    parser.add_argument(
        "--only",
        choices=["all", "ingest", "nlp", "dbt", "backtest"],
        default="all",
        help="Run only one task group.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print and log tasks without executing them.")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue remaining tasks after a failure.")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR, help="Directory for pipeline CSV logs.")
    parser.add_argument("--schedule", action="store_true", help="Run daily with APScheduler instead of one shot.")
    parser.add_argument("--hour", type=int, default=7, help="Daily scheduler hour.")
    parser.add_argument("--minute", type=int, default=0, help="Daily scheduler minute.")
    parser.add_argument(
        "--load-logs-to-bigquery",
        action="store_true",
        help="Append pipeline logs to raw.pipeline_logs_raw after the run.",
    )
    return parser.parse_args()


def run_subprocess(task: TaskSpec) -> CommandResult:
    process = subprocess.Popen(
        task.command,
        cwd=task.cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output_lines = []
    assert process.stdout is not None
    for line in process.stdout:
        output_lines.append(line)
        print(line, end="", flush=True)

    returncode = process.wait()
    output = "".join(output_lines)
    return CommandResult(
        returncode=returncode,
        stdout=output,
        stderr=output if returncode != 0 else "",
    )


def select_tasks(tasks: Iterable[TaskSpec], only: str) -> list[TaskSpec]:
    if only == "all":
        return list(tasks)
    return [task for task in tasks if task.group == only]


def run_task(
    task: TaskSpec,
    *,
    run_id: str,
    command_runner: CommandRunner = run_subprocess,
    dry_run: bool = False,
) -> PipelineLog:
    start_time = datetime.now(UTC)

    if dry_run:
        end_time = datetime.now(UTC)
        return PipelineLog(
            run_id=run_id,
            task_name=task.name,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            status=SKIPPED,
            duration_seconds=(end_time - start_time).total_seconds(),
            rows_processed=0,
            error_message="dry-run",
        )

    attempts = task.retries + 1
    last_error = None
    rows_processed = None

    for attempt in range(1, attempts + 1):
        result = command_runner(task)
        rows_processed = result.rows_processed
        if result.returncode == 0:
            end_time = datetime.now(UTC)
            return PipelineLog(
                run_id=run_id,
                task_name=task.name,
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                status=SUCCESS,
                duration_seconds=(end_time - start_time).total_seconds(),
                rows_processed=rows_processed,
            )

        last_error = result.stderr or result.stdout or f"Command failed with return code {result.returncode}"
        if attempt < attempts:
            time.sleep(task.retry_delay_seconds)

    end_time = datetime.now(UTC)
    return PipelineLog(
        run_id=run_id,
        task_name=task.name,
        start_time=start_time.isoformat(),
        end_time=end_time.isoformat(),
        status=FAILED,
        duration_seconds=(end_time - start_time).total_seconds(),
        rows_processed=rows_processed,
        error_message=last_error,
    )


def write_logs(logs: list[PipelineLog], log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    run_id = logs[0].run_id if logs else str(uuid.uuid4())
    output_path = log_dir / f"pipeline_{run_id}.csv"
    fieldnames = [
        "run_id",
        "task_name",
        "start_time",
        "end_time",
        "status",
        "duration_seconds",
        "rows_processed",
        "error_message",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for log in logs:
            writer.writerow(asdict(log))

    return output_path


def load_logs_to_bigquery(logs: list[PipelineLog], table_id: str | None = None) -> int:
    try:
        import pandas as pd
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError("pandas and google-cloud-bigquery are required to load pipeline logs.") from exc

    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    if not table_id:
        if not project_id:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT or GCP_PROJECT must be set to load logs into BigQuery.")
        table_id = os.getenv("PIPELINE_LOGS_TABLE", f"{project_id}.raw.pipeline_logs_raw")

    dataframe = pd.DataFrame([asdict(log) for log in logs])
    for column in ["start_time", "end_time"]:
        dataframe[column] = pd.to_datetime(dataframe[column], utc=True)

    client = bigquery.Client(project=project_id)
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    job = client.load_table_from_dataframe(dataframe, table_id, job_config=job_config)
    job.result()
    return len(dataframe)


def append_final_status(logs: list[PipelineLog], run_id: str) -> None:
    start_time = datetime.now(UTC)
    status = SUCCESS if all(log.status in {SUCCESS, SKIPPED} for log in logs) else FAILED
    failed_tasks = [log.task_name for log in logs if log.status == FAILED]
    logs.append(
        PipelineLog(
            run_id=run_id,
            task_name="final_status",
            start_time=start_time.isoformat(),
            end_time=datetime.now(UTC).isoformat(),
            status=status,
            duration_seconds=sum(log.duration_seconds for log in logs),
            rows_processed=sum(log.rows_processed or 0 for log in logs),
            error_message=", ".join(failed_tasks) if failed_tasks else None,
        )
    )


def run_pipeline(
    *,
    only: str = "all",
    dry_run: bool = False,
    continue_on_error: bool = False,
    log_dir: Path = DEFAULT_LOG_DIR,
    tasks: list[TaskSpec] | None = None,
    command_runner: CommandRunner = run_subprocess,
    load_logs_bigquery: bool = False,
) -> tuple[str, list[PipelineLog], Path]:
    run_id = str(uuid.uuid4())
    selected_tasks = select_tasks(tasks or default_tasks(), only)
    logs: list[PipelineLog] = []

    for task in selected_tasks:
        log = run_task(task, run_id=run_id, command_runner=command_runner, dry_run=dry_run)
        logs.append(log)
        print(f"{log.status.upper()} | {task.name} | {' '.join(task.command)}")
        if log.status == FAILED and not continue_on_error:
            break

    append_final_status(logs, run_id)
    log_path = write_logs(logs, log_dir)
    if load_logs_bigquery and not dry_run:
        rows = load_logs_to_bigquery(logs)
        print(f"Loaded {rows} pipeline log rows to BigQuery")
    print(f"Pipeline run_id={run_id} final_status={logs[-1].status} log_path={log_path}")
    return run_id, logs, log_path


def schedule_daily(args: argparse.Namespace) -> None:
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError as exc:
        raise RuntimeError("APScheduler is required for --schedule. Install requirements/requirements.txt.") from exc

    scheduler = BlockingScheduler(timezone="Europe/Paris")
    scheduler.add_job(
        lambda: run_pipeline(
            only=args.only,
            dry_run=args.dry_run,
            continue_on_error=args.continue_on_error,
            log_dir=args.log_dir,
            load_logs_bigquery=args.load_logs_to_bigquery,
        ),
        trigger="cron",
        hour=args.hour,
        minute=args.minute,
        id="daily_elt_pipeline",
        replace_existing=True,
    )
    print(f"Scheduler started: daily at {args.hour:02d}:{args.minute:02d} Europe/Paris")
    scheduler.start()


def main() -> int:
    args = parse_args()
    if args.schedule:
        schedule_daily(args)
        return 0

    _, logs, _ = run_pipeline(
        only=args.only,
        dry_run=args.dry_run,
        continue_on_error=args.continue_on_error,
        log_dir=args.log_dir,
        load_logs_bigquery=args.load_logs_to_bigquery,
    )
    return 0 if logs[-1].status == SUCCESS else 1


if __name__ == "__main__":
    raise SystemExit(main())
