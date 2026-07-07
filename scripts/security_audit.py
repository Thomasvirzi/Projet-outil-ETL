#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRS = {
    ".git",
    ".terraform",
    ".pytest_cache",
    "__pycache__",
    "dbt_packages",
    "target",
    "venv",
    ".venv",
    "data",
    "logs",
    "exports",
}
IGNORED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".parquet",
    ".duckdb",
    ".sqlite",
    ".db",
    ".DS_Store",
}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret|password|private[_-]?key|access[_-]?token)\s*[:=]\s*['\"][^'\"\n]{12,}['\"]"),
    re.compile(r"(?i)google_application_credentials\s*=\s*['\"][^'\"\n]+\.json['\"]"),
    re.compile(r"ya29\.[0-9A-Za-z_\-]+"),
]


@dataclass(frozen=True)
class SecretFinding:
    path: Path
    line_number: int
    pattern: str


def iter_scannable_files(root: Path = PROJECT_ROOT) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name in IGNORED_SUFFIXES or path.suffix in IGNORED_SUFFIXES:
            continue
        files.append(path)
    return files


def scan_file(path: Path, root: Path = PROJECT_ROOT) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return findings

    for line_number, line in enumerate(lines, start=1):
        for pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(
                    SecretFinding(
                        path=path.relative_to(root),
                        line_number=line_number,
                        pattern=pattern.pattern,
                    )
                )
    return findings


def scan_repository(root: Path = PROJECT_ROOT) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for path in iter_scannable_files(root):
        findings.extend(scan_file(path, root))
    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan repository files for obvious committed secrets.")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    findings = scan_repository(args.root)
    if findings:
        for finding in findings:
            print(f"{finding.path}:{finding.line_number} potential secret pattern={finding.pattern}")
        return 1
    print("No obvious committed secrets found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
