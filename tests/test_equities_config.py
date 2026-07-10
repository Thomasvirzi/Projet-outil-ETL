from scripts.extract_load.config import load_project_config


def test_equities_universe_has_twenty_enabled_tickers() -> None:
    config = load_project_config()

    assert len(config.enabled_equities) == 20


def test_equities_tickers_are_unique() -> None:
    config = load_project_config()

    tickers = [equity["ticker"] for equity in config.enabled_equities]

    assert len(tickers) == len(set(tickers))


def test_equities_universe_includes_expected_mix_of_currencies() -> None:
    config = load_project_config()

    currencies = {equity["currency"] for equity in config.enabled_equities}

    assert currencies == {"USD", "EUR"}


def test_market_benchmark_and_portfolio_defaults_are_configured() -> None:
    config = load_project_config()

    assert config.equities["market_benchmark"]["ticker"] == "SPY"
    assert config.equities["portfolio"]["reference_currency"] == "EUR"
    assert config.equities["portfolio"]["rebalance"] == "monthly"
