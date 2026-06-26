from pathlib import Path

from scripts.extract_load.config import (
    CONFIG_DIR,
    ProjectConfig,
    get_bigquery_table,
    load_project_config,
)


def test_load_project_config() -> None:
    config = load_project_config()

    assert isinstance(config, ProjectConfig)
    assert config.enabled_commodities
    assert config.enabled_rss_sources
    assert config.enabled_strategies


def test_bigquery_table_name() -> None:
    config = load_project_config()

    assert get_bigquery_table(config, "market_data_raw") == "raw.market_data_raw"


def test_no_secret_like_keys_in_yaml_config() -> None:
    forbidden_terms = ["password", "secret", "private_key", "token"]

    for path in Path(CONFIG_DIR).glob("*.yml"):
        content = path.read_text(encoding="utf-8").lower()
        for term in forbidden_terms:
            assert term not in content, f"Potential secret term found in {path}: {term}"
