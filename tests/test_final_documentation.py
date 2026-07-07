from pathlib import Path


def test_final_documentation_files_exist() -> None:
    expected_files = [
        "docs/installation_locale.md",
        "docs/config_terraform_GCP.md",
        "docs/architecture_globale.md",
        "docs/schema_base_donnees.md",
        "docs/flux_donnee.md",
        "docs/strategies_backtesting.md",
        "docs/hypotheses_limites_biais.md",
        "docs/documentation_finale.md",
        "docs/soutenance_slides.md",
        "VERSION",
    ]

    for relative_path in expected_files:
        assert Path(relative_path).exists(), relative_path


def test_version_file_declares_stable_mvp() -> None:
    assert Path("VERSION").read_text(encoding="utf-8").strip() == "1.0.0-mvp"


def test_final_documentation_index_mentions_soutenance_assets() -> None:
    index = Path("docs/documentation_finale.md").read_text(encoding="utf-8")

    assert "docs/soutenance_slides.md" in index
    assert "docs/strategies_backtesting.md" in index
    assert "docs/schema_base_donnees.md" in index
    assert "mart.mart_strategy_metrics" in index


def test_database_schema_documentation_contains_mermaid_diagrams() -> None:
    schema_doc = Path("docs/schema_base_donnees.md").read_text(encoding="utf-8")

    assert schema_doc.count("```mermaid") >= 4
    assert "erDiagram" in schema_doc
    assert "raw.market_data_raw" in schema_doc
    assert "mart_backtest_daily" in schema_doc
