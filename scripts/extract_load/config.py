from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


CONFIG_FILES = {
    "commodities": "commodities.yml",
    "benchmarks": "benchmarks.yml",
    "rss_sources": "rss_sources.yml",
    "strategies": "strategies.yml",
    "settings": "settings.yml",
}


class ConfigError(RuntimeError):
    """Raised when project configuration is missing or invalid."""


@dataclass(frozen=True)
class EnvironmentConfig:
    google_cloud_project: str | None
    google_application_credentials: Path | None
    bigquery_location: str
    environment: str
    log_level: str


@dataclass(frozen=True)
class ProjectConfig:
    commodities: dict[str, Any]
    benchmarks: dict[str, Any]
    rss_sources: dict[str, Any]
    strategies: dict[str, Any]
    settings: dict[str, Any]
    environment: EnvironmentConfig

    @property
    def enabled_commodities(self) -> list[dict[str, Any]]:
        return [
            commodity
            for commodity in self.commodities.get("commodities", [])
            if commodity.get("enabled", True)
        ]

    @property
    def enabled_rss_sources(self) -> list[dict[str, Any]]:
        return [
            source
            for source in self.rss_sources.get("rss_sources", [])
            if source.get("enabled", True)
        ]

    @property
    def enabled_strategies(self) -> dict[str, dict[str, Any]]:
        strategies = self.strategies.get("strategies", {})
        return {
            strategy_name: strategy_config
            for strategy_name, strategy_config in strategies.items()
            if strategy_config.get("enabled", True)
        }


def load_yaml_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Missing configuration file: {path}")

    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}

    if not isinstance(loaded, dict):
        raise ConfigError(f"Configuration file must contain a YAML mapping: {path}")

    return loaded


def load_environment(env_file: Path | None = None) -> EnvironmentConfig:
    load_dotenv(env_file or PROJECT_ROOT / ".env")

    credentials = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    return EnvironmentConfig(
        google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        google_application_credentials=Path(credentials).expanduser()
        if credentials
        else None,
        bigquery_location=os.getenv("BIGQUERY_LOCATION", "EU"),
        environment=os.getenv("ENVIRONMENT", "dev"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


def load_project_config(config_dir: Path = CONFIG_DIR) -> ProjectConfig:
    configs = {
        name: load_yaml_config(config_dir / filename)
        for name, filename in CONFIG_FILES.items()
    }

    project_config = ProjectConfig(
        commodities=configs["commodities"],
        benchmarks=configs["benchmarks"],
        rss_sources=configs["rss_sources"],
        strategies=configs["strategies"],
        settings=configs["settings"],
        environment=load_environment(),
    )

    validate_project_config(project_config)
    return project_config


def validate_project_config(config: ProjectConfig) -> None:
    if not config.commodities.get("commodities"):
        raise ConfigError("At least one commodity must be configured.")

    if not config.benchmarks.get("benchmarks"):
        raise ConfigError("Benchmark configuration is required.")

    if not config.rss_sources.get("rss_sources"):
        raise ConfigError("At least one RSS source must be configured.")

    if not config.strategies.get("strategies"):
        raise ConfigError("At least one strategy must be configured.")

    required_settings_sections = ["pipeline", "paths", "bigquery", "nlp"]
    missing_sections = [
        section
        for section in required_settings_sections
        if section not in config.settings
    ]
    if missing_sections:
        joined_sections = ", ".join(missing_sections)
        raise ConfigError(f"Missing settings sections: {joined_sections}")

    commodity_symbols = [
        commodity.get("symbol")
        for commodity in config.commodities.get("commodities", [])
    ]
    if len(commodity_symbols) != len(set(commodity_symbols)):
        raise ConfigError("Commodity symbols must be unique.")

    rss_names = [
        source.get("name")
        for source in config.rss_sources.get("rss_sources", [])
    ]
    if len(rss_names) != len(set(rss_names)):
        raise ConfigError("RSS source names must be unique.")


def get_bigquery_table(config: ProjectConfig, table_key: str) -> str:
    bigquery_config = config.settings["bigquery"]
    raw_dataset = bigquery_config["raw_dataset"]
    table_name = bigquery_config["tables"][table_key]
    return f"{raw_dataset}.{table_name}"


if __name__ == "__main__":
    loaded_config = load_project_config()
    print("Configuration loaded successfully.")
    print(f"Environment: {loaded_config.environment.environment}")
    print(f"Enabled commodities: {len(loaded_config.enabled_commodities)}")
    print(f"Enabled RSS sources: {len(loaded_config.enabled_rss_sources)}")
    print(f"Enabled strategies: {', '.join(loaded_config.enabled_strategies)}")
