#!/usr/bin/env python3
"""
Construit des benchmarks Buy & Hold et un indice synthétique de matières
premières à partir de données Yahoo Finance téléchargées avec yfinance.

Le script peut fonctionner de deux façons :
1. téléchargement direct depuis yfinance, mode par défaut ;
2. lecture du CSV propre produit par commodities_pipeline.py avec --input-csv.

Sorties principales :
- yfinance_close_prices.csv
- buy_hold_price_indices.csv
- synthetic_commodity_index.csv
- synthetic_index_weights.csv
- benchmark_comparison.csv
- benchmark_metrics.csv
- benchmark_run_config.json

Exemple :
    python commodity_benchmark_index.py \
        --start-date 2015-01-01 \
        --priorities A \
        --weighting equal \
        --rebalance monthly \
        --output-dir data/benchmarks

Important : les tickers Yahoo Finance de type '=F' sont utilisés comme séries
continues de prix. Le résultat est donc un benchmark de recherche fondé sur les
prix Yahoo, et non la réplication exacte d'un indice futures investissable avec
contrats datés, roll explicite, collatéral et multiplicateurs de contrats.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf


# ============================================================
# UNIVERS D'ACTIFS
# ============================================================

# (asset_id, nom, ticker Yahoo Finance, catégorie, priorité)
_COMMODITIES_TABLE: list[tuple[str, str, str, str, str]] = [
    ("WTI", "Pétrole WTI", "CL=F", "Énergie", "A"),
    ("GOLD", "Or", "GC=F", "Métaux précieux", "A"),
    ("NATURAL_GAS", "Gaz naturel Henry Hub", "NG=F", "Énergie", "A"),
    ("COPPER", "Cuivre", "HG=F", "Métaux industriels", "A"),
    ("WHEAT", "Blé Chicago SRW", "ZW=F", "Agriculture", "A"),
    ("CORN", "Maïs", "ZC=F", "Agriculture", "A"),
    ("COCOA", "Cacao", "CC=F", "Soft commodities", "A"),
    ("COFFEE", "Café Arabica", "KC=F", "Soft commodities", "A"),
    ("BRENT", "Pétrole Brent", "BZ=F", "Énergie", "B"),
    ("SILVER", "Argent", "SI=F", "Métaux précieux", "B"),
    ("SOYBEAN", "Soja", "ZS=F", "Agriculture", "B"),
    ("SUGAR", "Sucre No. 11", "SB=F", "Soft commodities", "B"),
    ("PLATINUM", "Platine", "PL=F", "Métaux précieux", "C"),
    ("PALLADIUM", "Palladium", "PA=F", "Métaux précieux", "C"),
    ("COTTON", "Coton", "CT=F", "Agriculture", "C"),
    ("ORANGE_JUICE", "Jus d'orange concentré", "OJ=F", "Soft commodities", "C"),
    ("ROUGH_RICE", "Riz brut", "ZR=F", "Agriculture", "C"),
    ("LUMBER", "Bois d'œuvre", "LBR=F", "Matériaux", "C"),
    ("OLIVE_OIL_PROXY", "Huile d'olive (proxy ETF ASX)", "CBO.AX", "Agriculture", "C"),
    ("LITHIUM_HYDROXIDE", "Lithium hydroxyde (futures)", "LTH=F", "Métaux industriels", "C"),
]

COMMODITIES: dict[str, dict[str, str]] = {
    asset_id: {"name": name, "ticker": ticker, "category": category, "priority": priority}
    for asset_id, name, ticker, category, priority in _COMMODITIES_TABLE
}

PRICE_FIELD_MAP = {
    "close": "Close",
    "adj_close": "Adj Close",
}

REBALANCE_PERIOD_MAP = {
    "monthly": "M",
    "quarterly": "Q",
    "annual": "Y",
}


# ============================================================
# STRUCTURES
# ============================================================

@dataclass(frozen=True)
class IndexConfig:
    base_value: float
    weighting: str
    rebalance: str
    vol_lookback: int
    min_vol_observations: int
    transaction_cost_bps: float
    annual_risk_free_rate: float
    max_forward_fill: int
    price_field: str


# ============================================================
# LOGGING ET CLI
# ============================================================

def configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Crée des benchmarks Buy & Hold et un indice synthétique de "
            "matières premières à partir de yfinance."
        )
    )

    source_group = parser.add_argument_group("Source de données")
    source_group.add_argument(
        "--input-csv",
        type=Path,
        default=None,
        help=(
            "CSV propre au format long issu de commodities_pipeline.py. "
            "Sans cette option, les données sont téléchargées depuis yfinance."
        ),
    )
    source_group.add_argument(
        "--start-date",
        default="2015-01-01",
        help="Date de début yfinance au format YYYY-MM-DD.",
    )
    source_group.add_argument(
        "--end-date",
        default=None,
        help="Date de fin yfinance au format YYYY-MM-DD. Défaut : aujourd'hui.",
    )
    source_group.add_argument(
        "--price-field",
        choices=["close", "adj_close"],
        default="close",
        help="Champ utilisé pour les calculs. Défaut : close.",
    )

    universe_group = parser.add_argument_group("Univers")
    universe_group.add_argument(
        "--priorities",
        nargs="+",
        choices=["A", "B", "C"],
        default=["A", "B", "C"],
        help="Priorités incluses. Exemple : --priorities A B",
    )
    universe_group.add_argument(
        "--asset-ids",
        nargs="+",
        choices=sorted(COMMODITIES),
        default=None,
        help=(
            "Liste explicite d'actifs. Cette option prend le pas sur --priorities. "
            "Exemple : --asset-ids WTI GOLD COPPER"
        ),
    )

    index_group = parser.add_argument_group("Méthodologie de l'indice")
    index_group.add_argument(
        "--base-value",
        type=float,
        default=100.0,
        help="Valeur initiale des séries. Défaut : 100.",
    )
    index_group.add_argument(
        "--weighting",
        choices=["equal", "inverse_vol"],
        default="equal",
        help=(
            "equal : poids égaux ; inverse_vol : poids inversement "
            "proportionnels à la volatilité historique."
        ),
    )
    index_group.add_argument(
        "--rebalance",
        choices=["none", "monthly", "quarterly", "annual"],
        default="monthly",
        help="Fréquence de rebalancement. Défaut : monthly.",
    )
    index_group.add_argument(
        "--vol-lookback",
        type=int,
        default=60,
        help="Fenêtre de volatilité en séances pour inverse_vol. Défaut : 60.",
    )
    index_group.add_argument(
        "--min-vol-observations",
        type=int,
        default=20,
        help="Nombre minimal d'observations pour estimer la volatilité.",
    )
    index_group.add_argument(
        "--transaction-cost-bps",
        type=float,
        default=0.0,
        help="Coût appliqué au turnover à chaque rebalancement, en points de base.",
    )
    index_group.add_argument(
        "--max-forward-fill",
        type=int,
        default=3,
        help=(
            "Nombre maximal de séances pour reporter un dernier prix connu "
            "lors de l'alignement des calendriers. Défaut : 3."
        ),
    )
    index_group.add_argument(
        "--annual-risk-free-rate",
        type=float,
        default=0.0,
        help="Taux sans risque annuel utilisé pour le Sharpe, en décimal.",
    )

    output_group = parser.add_argument_group("Sorties")
    output_group.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/benchmarks"),
        help="Dossier de sortie. Défaut : data/benchmarks",
    )
    output_group.add_argument(
        "--verbose",
        action="store_true",
        help="Active les logs détaillés.",
    )

    return parser.parse_args()


# ============================================================
# SÉLECTION ET CHARGEMENT
# ============================================================

def select_assets(
    priorities: set[str],
    asset_ids: list[str] | None,
) -> dict[str, dict[str, str]]:
    if asset_ids:
        selected = {asset_id: COMMODITIES[asset_id] for asset_id in asset_ids}
    else:
        selected = {
            asset_id: config
            for asset_id, config in COMMODITIES.items()
            if config["priority"] in priorities
        }

    if len(selected) < 2:
        raise ValueError(
            "L'indice synthétique nécessite au moins deux actifs sélectionnés."
        )

    return selected


def _download_single_ticker(
    ticker: str,
    start_date: str,
    end_date: str | None,
) -> pd.DataFrame:
    kwargs: dict[str, Any] = {
        "tickers": ticker,
        "start": start_date,
        "end": end_date,
        "interval": "1d",
        "auto_adjust": False,
        "progress": False,
        "threads": False,
    }

    # multi_level_index est disponible dans les versions récentes de yfinance.
    # Le fallback conserve la compatibilité avec des versions plus anciennes.
    try:
        data = yf.download(**kwargs, multi_level_index=False)
    except TypeError:
        data = yf.download(**kwargs)

    if data is None or data.empty:
        raise ValueError("Aucune donnée retournée par yfinance")

    if isinstance(data.columns, pd.MultiIndex):
        # Level 0 = price field (Open, Close, …), level 1 = ticker symbol
        # If level 0 only contains ticker names, price fields are at level 1
        price_fields = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
        if not (price_fields & set(data.columns.get_level_values(0))):
            data.columns = data.columns.get_level_values(1)
        else:
            data.columns = data.columns.get_level_values(0)

    # Drop duplicate columns that can appear with certain yfinance versions
    if data.columns.duplicated().any():
        data = data.loc[:, ~data.columns.duplicated()]

    return data


def _fetch_asset_series(
    asset_id: str,
    config: dict[str, str],
    start_date: str,
    end_date: str | None,
    yahoo_column: str,
    price_field: str,
) -> tuple[str, pd.Series | None, dict[str, str] | None]:
    ticker = config["ticker"]
    try:
        data = _download_single_ticker(ticker, start_date, end_date)

        chosen_column = yahoo_column
        if chosen_column not in data.columns:
            if price_field == "adj_close" and "Close" in data.columns:
                logging.warning(
                    "%s ne fournit pas Adj Close ; utilisation de Close.", ticker
                )
                chosen_column = "Close"
            else:
                raise ValueError(
                    f"Colonne {yahoo_column!r} absente. Colonnes : {list(data.columns)}"
                )

        col_data = data[chosen_column]
        if isinstance(col_data, pd.DataFrame):
            col_data = col_data.iloc[:, 0]
        series = pd.to_numeric(col_data, errors="coerce")
        series.index = pd.to_datetime(series.index, utc=True, errors="coerce")
        series = series[~series.index.isna()]
        series.name = asset_id

        logging.info("%s : %s observations", asset_id, f"{series.notna().sum():,}")
        return asset_id, series, None

    except Exception as exc:
        logging.exception("Échec du téléchargement de %s", ticker)
        return asset_id, None, {"asset_id": asset_id, "ticker": ticker, "error": str(exc)}


def download_price_panel(
    selected_assets: dict[str, dict[str, str]],
    start_date: str,
    end_date: str | None,
    price_field: str,
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    yahoo_column = PRICE_FIELD_MAP[price_field]
    results: dict[str, pd.Series] = {}
    errors: list[dict[str, str]] = []

    max_workers = min(8, len(selected_assets))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _fetch_asset_series,
                asset_id, config, start_date, end_date, yahoo_column, price_field,
            ): asset_id
            for asset_id, config in selected_assets.items()
        }
        for future in as_completed(futures):
            asset_id, series, error = future.result()
            if series is not None:
                results[asset_id] = series
            else:
                errors.append(error)

    # Preserve selection order
    series_list = [results[aid] for aid in selected_assets if aid in results]

    if len(series_list) < 2:
        raise RuntimeError(
            "Moins de deux séries ont été téléchargées ; indice impossible à calculer."
        )

    prices = pd.concat(series_list, axis=1).sort_index()
    # Normalise le nom de l'index (yfinance retourne "Date" avec majuscule)
    prices.index.name = "date"
    return prices, errors


def load_price_panel_from_csv(
    csv_path: Path,
    selected_assets: dict[str, dict[str, str]],
    price_field: str,
) -> pd.DataFrame:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV introuvable : {csv_path}")

    data = pd.read_csv(csv_path)
    required = {"date", "commodity_id", price_field}
    missing = required.difference(data.columns)

    if missing:
        raise ValueError(
            f"Colonnes absentes du CSV : {sorted(missing)}. "
            f"Colonnes disponibles : {list(data.columns)}"
        )

    data["date"] = pd.to_datetime(data["date"], utc=True, errors="coerce")
    data[price_field] = pd.to_numeric(data[price_field], errors="coerce")
    data = data.dropna(subset=["date", "commodity_id", price_field])
    data = data[data["commodity_id"].isin(selected_assets)]

    prices = data.pivot_table(
        index="date",
        columns="commodity_id",
        values=price_field,
        aggfunc="last",
    ).sort_index()

    missing_assets = sorted(set(selected_assets).difference(prices.columns))
    if missing_assets:
        raise ValueError(
            "Actifs demandés absents du CSV : " + ", ".join(missing_assets)
        )

    return prices[list(selected_assets)]


def align_price_panel(
    prices: pd.DataFrame,
    selected_assets: dict[str, dict[str, str]],
    max_forward_fill: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Aligne les calendriers sans backfill, afin de ne pas introduire de futur.

    Le dernier prix connu peut être reporté sur un nombre limité de séances.
    Le rapport returned indique quelles valeurs ont été reportées.
    """
    prices = prices.copy()
    prices = prices.reindex(columns=list(selected_assets))
    prices = prices[~prices.index.duplicated(keep="last")].sort_index()
    prices = prices.replace([np.inf, -np.inf], np.nan)

    observed_mask = prices.notna()
    aligned = prices.ffill(limit=max_forward_fill)
    filled_mask = aligned.notna() & ~observed_mask

    # Une période comparable commence uniquement lorsque tous les actifs ont un prix.
    aligned = aligned.dropna(how="any")
    filled_mask = filled_mask.reindex(aligned.index).fillna(False).astype(bool)

    if aligned.empty:
        raise ValueError(
            "Aucune période commune complète après alignement des calendriers."
        )

    if len(aligned) < 3:
        raise ValueError("Historique commun insuffisant pour calculer les benchmarks.")

    return aligned.astype(float), filled_mask


# ============================================================
# CALCUL DES POIDS ET DE L'INDICE
# ============================================================

def get_rebalance_flags(
    dates: pd.DatetimeIndex,
    rebalance: str,
) -> pd.Series:
    flags = pd.Series(False, index=dates)
    flags.iloc[0] = True

    if rebalance == "none" or len(dates) == 1:
        return flags

    period_frequency = REBALANCE_PERIOD_MAP[rebalance]
    naive_dates = dates.tz_convert(None) if dates.tz is not None else dates
    periods = naive_dates.to_period(period_frequency)
    flags.iloc[1:] = np.asarray(periods[1:] != periods[:-1])

    return flags


def _resolve_target_weights(
    weighting: str,
    equal_weights: np.ndarray,
    rolling_vol: pd.DataFrame | None,
    asset_ids: list[str],
    position: int,
) -> np.ndarray:
    """Poids cible à la date `position`, fondés sur la volatilité connue la veille (pas d'anticipation)."""
    if weighting == "equal":
        return equal_weights.copy()

    vol = rolling_vol.iloc[position - 1].values  # type: ignore[union-attr]
    if not (np.isfinite(vol).all() and (vol > 0).all()):
        excluded = [asset_ids[i] for i, ok in enumerate(np.isfinite(vol) & (vol > 0)) if not ok]
        raise ValueError(
            "Volatilité impossible à estimer pour : "
            + ", ".join(excluded)
            + ". Augmenter l'historique ou réduire --min-vol-observations."
        )
    inv_vol = 1.0 / vol
    return inv_vol / inv_vol.sum()


def build_synthetic_index(
    prices: pd.DataFrame,
    config: IndexConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    asset_ids = list(prices.columns)
    n_assets = len(asset_ids)
    returns = prices.pct_change(fill_method=None)

    # Pré-calcul vectorisé de la volatilité rolling (évite le recalcul à chaque rebalancement)
    rolling_vol: pd.DataFrame | None = None
    if config.weighting == "inverse_vol":
        start_position = max(config.vol_lookback, config.min_vol_observations)
        if len(prices) <= start_position:
            raise ValueError("Historique insuffisant pour la pondération inverse_vol.")
        rolling_vol = returns.rolling(
            config.vol_lookback, min_periods=config.min_vol_observations
        ).std(ddof=1)
    else:
        start_position = 0

    # Poids égaux pré-calculés une seule fois
    equal_weights = np.full(n_assets, 1.0 / n_assets)

    index_dates = prices.index[start_position:]
    rebalance_flags = get_rebalance_flags(index_dates, config.rebalance)

    # Tableaux numpy pour accès rapide dans la boucle
    prices_arr = prices.values  # shape (T, N)
    prices_index = prices.index

    units_arr: np.ndarray | None = None
    previous_level: float | None = None
    index_records: list[dict[str, Any]] = []

    # Accumulation des poids sous forme de tableaux pour construction finale en une passe
    weight_dates: list = []
    actual_weights_list: list[np.ndarray] = []
    target_weights_list: list[np.ndarray | None] = []
    rebalance_executed_list: list[bool] = []

    for date_position, date in enumerate(index_dates):
        full_position = prices_index.get_loc(date)
        cur_prices = prices_arr[full_position]  # numpy array, pas de Series

        rebalance_requested = bool(rebalance_flags.iloc[date_position])
        rebalance_executed = False
        rebalance_skipped = False
        turnover = 0.0
        transaction_cost = 0.0
        target_w: np.ndarray | None = None

        if units_arr is None:
            if (cur_prices <= 0).any():
                invalid = [asset_ids[i] for i, v in enumerate(cur_prices) if v <= 0]
                raise ValueError("Prix initial non positif pour : " + ", ".join(invalid))

            target_w = _resolve_target_weights(
                config.weighting, equal_weights, rolling_vol, asset_ids, full_position
            )

            units_arr = config.base_value * target_w / cur_prices
            index_level = config.base_value
            gross_index_level = config.base_value
            rebalance_executed = True

        else:
            position_values_before = units_arr * cur_prices
            gross_index_level = float(position_values_before.sum())

            if not math.isfinite(gross_index_level):
                raise ValueError(f"Valeur d'indice non finie à la date {date}.")

            index_level = gross_index_level

            if rebalance_requested:
                if gross_index_level <= 0 or (cur_prices <= 0).any():
                    rebalance_skipped = True
                    logging.warning(
                        "Rebalancement ignoré le %s en raison d'un prix ou niveau non positif.",
                        date.date(),
                    )
                else:
                    target_w = _resolve_target_weights(
                        config.weighting, equal_weights, rolling_vol, asset_ids, full_position
                    )

                    current_weights = position_values_before / gross_index_level
                    turnover = float(0.5 * np.abs(target_w - current_weights).sum())
                    transaction_cost = float(
                        gross_index_level * turnover * config.transaction_cost_bps / 10_000.0
                    )
                    index_level = gross_index_level - transaction_cost

                    if index_level <= 0:
                        raise ValueError(f"Les coûts rendent l'indice non positif le {date}.")

                    units_arr = index_level * target_w / cur_prices
                    rebalance_executed = True

        assert units_arr is not None

        position_values_after = units_arr * cur_prices
        total_after = position_values_after.sum()
        actual_w = position_values_after / total_after

        daily_return = np.nan if previous_level is None else index_level / previous_level - 1.0

        index_records.append({
            "date": date,
            "index_level": index_level,
            "gross_index_level": gross_index_level,
            "daily_return": daily_return,
            "rebalance_requested": rebalance_requested,
            "rebalance_executed": rebalance_executed,
            "rebalance_skipped": rebalance_skipped,
            "turnover": turnover,
            "transaction_cost": transaction_cost,
        })

        weight_dates.append(date)
        actual_weights_list.append(actual_w)
        target_weights_list.append(target_w)
        rebalance_executed_list.append(rebalance_executed)

        previous_level = index_level

    index_df = pd.DataFrame(index_records).set_index("date")
    index_df["running_peak"] = index_df["index_level"].cummax()
    index_df["drawdown"] = index_df["index_level"] / index_df["running_peak"] - 1.0

    # Construction du DataFrame des poids en une seule passe (évite la boucle interne)
    n_dates = len(weight_dates)
    actual_arr = np.stack(actual_weights_list)   # (T, N)
    target_arr = np.full((n_dates, n_assets), np.nan)
    for i, tw in enumerate(target_weights_list):
        if tw is not None:
            target_arr[i] = tw

    weights_df = pd.DataFrame({
        "date": np.repeat(weight_dates, n_assets),
        "asset_id": np.tile(asset_ids, n_dates),
        "actual_weight": actual_arr.ravel(),
        "target_weight": target_arr.ravel(),
        "rebalance_executed": np.repeat(rebalance_executed_list, n_assets),
    })

    return index_df, weights_df


# ============================================================
# BUY & HOLD ET MÉTRIQUES
# ============================================================

def build_buy_and_hold_indices(
    prices: pd.DataFrame,
    start_date: pd.Timestamp,
    base_value: float,
) -> pd.DataFrame:
    aligned = prices.loc[start_date:].copy()
    initial_prices = aligned.iloc[0]

    if (initial_prices == 0).any():
        invalid = list(initial_prices.index[initial_prices == 0])
        raise ValueError("Prix initial nul pour : " + ", ".join(invalid))

    buy_hold = aligned.divide(initial_prices).multiply(base_value)
    buy_hold.columns = [f"BH_{asset_id}" for asset_id in buy_hold.columns]
    return buy_hold


def calculate_series_metrics(
    series: pd.Series,
    annual_risk_free_rate: float,
    annualization_factor: int = 252,
) -> dict[str, Any]:
    clean = pd.to_numeric(series, errors="coerce").dropna()

    if len(clean) < 2:
        return {
            "start_date": None,
            "end_date": None,
            "observations": len(clean),
            "total_return": np.nan,
            "cagr": np.nan,
            "annualized_volatility": np.nan,
            "sharpe_ratio": np.nan,
            "max_drawdown": np.nan,
            "non_positive_levels": int((clean <= 0).sum()),
        }

    returns = clean.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    returns = returns.dropna()

    total_return = (
        clean.iloc[-1] / clean.iloc[0] - 1.0
        if clean.iloc[0] != 0
        else np.nan
    )

    elapsed_years = (clean.index[-1] - clean.index[0]).days / 365.25
    if elapsed_years > 0 and clean.iloc[0] > 0 and clean.iloc[-1] > 0:
        cagr = (clean.iloc[-1] / clean.iloc[0]) ** (1.0 / elapsed_years) - 1.0
    else:
        cagr = np.nan

    annualized_volatility = (
        float(returns.std(ddof=1) * np.sqrt(annualization_factor))
        if len(returns) > 1
        else np.nan
    )

    risk_free_daily = (
        (1.0 + annual_risk_free_rate) ** (1.0 / annualization_factor) - 1.0
    )
    excess_returns = returns - risk_free_daily

    sharpe_ratio = (
        float(
            excess_returns.mean()
            / returns.std(ddof=1)
            * np.sqrt(annualization_factor)
        )
        if len(returns) > 1 and returns.std(ddof=1) > 0
        else np.nan
    )

    running_peak = clean.cummax()
    drawdown = clean.divide(running_peak.replace(0, np.nan)) - 1.0

    return {
        "start_date": clean.index[0],
        "end_date": clean.index[-1],
        "observations": len(clean),
        "total_return": float(total_return),
        "cagr": float(cagr) if pd.notna(cagr) else np.nan,
        "annualized_volatility": annualized_volatility,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": float(drawdown.min()),
        "non_positive_levels": int((clean <= 0).sum()),
    }


def build_metrics_table(
    comparison_df: pd.DataFrame,
    selected_assets: dict[str, dict[str, str]],
    annual_risk_free_rate: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for column in comparison_df.columns:
        if column == "SYNTHETIC_INDEX":
            asset_id = "SYNTHETIC_INDEX"
            display_name = "Indice synthétique"
            benchmark_type = "synthetic_index"
        else:
            asset_id = column.removeprefix("BH_")
            display_name = selected_assets[asset_id]["name"]
            benchmark_type = "buy_and_hold_price_proxy"

        metrics = calculate_series_metrics(
            comparison_df[column],
            annual_risk_free_rate=annual_risk_free_rate,
        )

        rows.append(
            {
                "series_id": column,
                "asset_id": asset_id,
                "display_name": display_name,
                "benchmark_type": benchmark_type,
                **metrics,
            }
        )

    return pd.DataFrame(rows)


# ============================================================
# DATASET CONSOLIDÉ
# ============================================================

def build_master_dataset(
    aligned_prices: pd.DataFrame,
    buy_hold_df: pd.DataFrame,
    index_df: pd.DataFrame,
    weights_df: pd.DataFrame,
    selected_assets: dict[str, dict[str, str]],
) -> pd.DataFrame:
    prices_long = aligned_prices.reset_index().melt(
        id_vars="date",
        var_name="commodity_id",
        value_name="close_price",
    )

    bh_renamed = buy_hold_df.copy()
    bh_renamed.columns = [c.removeprefix("BH_") for c in bh_renamed.columns]
    bh_long = bh_renamed.reset_index().melt(
        id_vars="date",
        var_name="commodity_id",
        value_name="buy_hold_index",
    )

    bh_returns = bh_renamed.pct_change(fill_method=None)
    bh_returns_long = bh_returns.reset_index().melt(
        id_vars="date",
        var_name="commodity_id",
        value_name="buy_hold_daily_return",
    )

    weights_renamed = weights_df.rename(columns={"asset_id": "commodity_id"})

    synth = (
        index_df[["index_level", "daily_return", "drawdown"]]
        .rename(columns={
            "index_level": "synthetic_index_level",
            "daily_return": "synthetic_index_return",
            "drawdown": "synthetic_index_drawdown",
        })
        .reset_index()
    )

    meta_df = pd.DataFrame([
        {
            "commodity_id": asset_id,
            "commodity_name": metadata["name"],
            "ticker": metadata["ticker"],
            "category": metadata["category"],
            "priority": metadata["priority"],
        }
        for asset_id, metadata in selected_assets.items()
    ])

    df = prices_long
    df = df.merge(bh_long, on=["date", "commodity_id"], how="left")
    df = df.merge(bh_returns_long, on=["date", "commodity_id"], how="left")
    df = df.merge(weights_renamed, on=["date", "commodity_id"], how="left")
    df = df.merge(synth, on="date", how="left")
    df = df.merge(meta_df, on="commodity_id", how="left")

    col_order = [
        "date", "commodity_id", "commodity_name", "ticker", "category", "priority",
        "close_price",
        "buy_hold_index", "buy_hold_daily_return",
        "actual_weight", "target_weight", "rebalance_executed",
        "synthetic_index_level", "synthetic_index_return", "synthetic_index_drawdown",
    ]
    df = df[[c for c in col_order if c in df.columns]]
    df = df.sort_values(["commodity_id", "date"]).reset_index(drop=True)
    return df


# ============================================================
# SAUVEGARDE
# ============================================================

def save_csv_atomic(
    dataframe: pd.DataFrame,
    output_path: Path,
    index: bool = True,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    dataframe.to_csv(
        temp_path,
        index=index,
        encoding="utf-8",
        date_format="%Y-%m-%d",
    )
    temp_path.replace(output_path)


def save_json_atomic(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temp_path.replace(output_path)


# ============================================================
# PIPELINE
# ============================================================

def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    selected_assets = select_assets(set(args.priorities), args.asset_ids)

    config = IndexConfig(
        base_value=args.base_value,
        weighting=args.weighting,
        rebalance=args.rebalance,
        vol_lookback=args.vol_lookback,
        min_vol_observations=args.min_vol_observations,
        transaction_cost_bps=args.transaction_cost_bps,
        annual_risk_free_rate=args.annual_risk_free_rate,
        max_forward_fill=args.max_forward_fill,
        price_field=args.price_field,
    )

    if config.base_value <= 0:
        raise ValueError("--base-value doit être strictement positif.")
    if config.vol_lookback < 2:
        raise ValueError("--vol-lookback doit être supérieur ou égal à 2.")
    if config.min_vol_observations < 2:
        raise ValueError("--min-vol-observations doit être supérieur ou égal à 2.")
    if config.transaction_cost_bps < 0:
        raise ValueError("--transaction-cost-bps ne peut pas être négatif.")
    if config.max_forward_fill < 0:
        raise ValueError("--max-forward-fill ne peut pas être négatif.")

    logging.info(
        "Univers : %s actifs | pondération=%s | rebalancement=%s",
        len(selected_assets),
        config.weighting,
        config.rebalance,
    )

    download_errors: list[dict[str, str]] = []

    if args.input_csv is not None:
        logging.info("Lecture du dataset yfinance existant : %s", args.input_csv)
        raw_prices = load_price_panel_from_csv(
            csv_path=args.input_csv,
            selected_assets=selected_assets,
            price_field=config.price_field,
        )
        source_type = "yfinance_clean_csv"
    else:
        raw_prices, download_errors = download_price_panel(
            selected_assets=selected_assets,
            start_date=args.start_date,
            end_date=args.end_date,
            price_field=config.price_field,
        )
        source_type = "yfinance_direct"

        if download_errors:
            failed_assets = {error["asset_id"] for error in download_errors}
            selected_assets = {
                asset_id: metadata
                for asset_id, metadata in selected_assets.items()
                if asset_id not in failed_assets
            }
            raw_prices = raw_prices.reindex(columns=list(selected_assets))

            if len(selected_assets) < 2:
                raise RuntimeError(
                    "Trop d'échecs de téléchargement pour construire un indice."
                )

    aligned_prices, filled_mask = align_price_panel(
        raw_prices,
        selected_assets=selected_assets,
        max_forward_fill=config.max_forward_fill,
    )

    non_positive_counts = (aligned_prices <= 0).sum()
    problematic = non_positive_counts[non_positive_counts > 0]
    if not problematic.empty:
        logging.warning(
            "Prix non positifs détectés : %s. Les benchmarks restent des "
            "indices de prix de recherche, pas des NAV d'ETF réplicables.",
            problematic.to_dict(),
        )

    index_df, weights_df = build_synthetic_index(aligned_prices, config)

    buy_hold_df = build_buy_and_hold_indices(
        prices=aligned_prices,
        start_date=index_df.index[0],
        base_value=config.base_value,
    )

    comparison_df = pd.concat(
        [
            index_df["index_level"].rename("SYNTHETIC_INDEX"),
            buy_hold_df,
        ],
        axis=1,
        join="inner",
    )

    metrics_df = build_metrics_table(
        comparison_df=comparison_df,
        selected_assets=selected_assets,
        annual_risk_free_rate=config.annual_risk_free_rate,
    )

    metadata_df = pd.DataFrame(
        [
            {
                "asset_id": asset_id,
                **metadata,
                "non_positive_price_count": int(
                    non_positive_counts.get(asset_id, 0)
                ),
                "forward_filled_price_count": int(
                    filled_mask[asset_id].sum()
                ),
            }
            for asset_id, metadata in selected_assets.items()
        ]
    )

    master_df = build_master_dataset(
        aligned_prices=aligned_prices,
        buy_hold_df=buy_hold_df,
        index_df=index_df,
        weights_df=weights_df,
        selected_assets=selected_assets,
    )

    output_dir: Path = args.output_dir
    paths = {
        "master_dataset": output_dir / "commodity_benchmark_dataset.csv",
        "prices": output_dir / "yfinance_close_prices.csv",
        "buy_hold": output_dir / "buy_hold_price_indices.csv",
        "synthetic_index": output_dir / "synthetic_commodity_index.csv",
        "weights": output_dir / "synthetic_index_weights.csv",
        "comparison": output_dir / "benchmark_comparison.csv",
        "metrics": output_dir / "benchmark_metrics.csv",
        "metadata": output_dir / "benchmark_assets_metadata.csv",
        "download_errors": output_dir / "download_errors.csv",
        "config": output_dir / "benchmark_run_config.json",
    }

    save_csv_atomic(master_df, paths["master_dataset"], index=False)
    save_csv_atomic(aligned_prices, paths["prices"], index=True)
    save_csv_atomic(buy_hold_df, paths["buy_hold"], index=True)
    save_csv_atomic(index_df, paths["synthetic_index"], index=True)
    save_csv_atomic(weights_df, paths["weights"], index=False)
    save_csv_atomic(comparison_df, paths["comparison"], index=True)
    save_csv_atomic(metrics_df, paths["metrics"], index=False)
    save_csv_atomic(metadata_df, paths["metadata"], index=False)

    if download_errors:
        save_csv_atomic(
            pd.DataFrame(download_errors),
            paths["download_errors"],
            index=False,
        )

    config_payload = {
        "source_type": source_type,
        "input_csv": str(args.input_csv) if args.input_csv else None,
        "start_date_requested": args.start_date,
        "end_date_requested": args.end_date,
        "first_common_price_date": aligned_prices.index[0],
        "last_common_price_date": aligned_prices.index[-1],
        "index_start_date": index_df.index[0],
        "selected_assets": selected_assets,
        "index_config": asdict(config),
        "methodology_note": (
            "Indice de prix synthétique utilisant les séries continues '=F' "
            "de Yahoo Finance. Il ne reproduit pas exactement le roll de contrats "
            "datés, les multiplicateurs, la marge ou le rendement du collatéral."
        ),
    }
    save_json_atomic(config_payload, paths["config"])

    logging.info(
        "Calcul terminé : %s à %s | %s observations d'indice | %s lignes dans le dataset",
        index_df.index[0].date(),
        index_df.index[-1].date(),
        f"{len(index_df):,}",
        f"{len(master_df):,}",
    )
    logging.info("Résultats sauvegardés dans %s", output_dir.resolve())

    return {
        "paths": paths,
        "rows": {
            "master_dataset": len(master_df),
            "prices": len(aligned_prices),
            "index": len(index_df),
            "weights": len(weights_df),
        },
        "download_errors": download_errors,
    }


def main() -> int:
    args = parse_args()
    configure_logging(args.verbose)

    try:
        run_pipeline(args)
        return 0
    except KeyboardInterrupt:
        logging.warning("Exécution interrompue par l'utilisateur.")
        return 130
    except Exception:
        logging.exception("Échec de la construction des benchmarks.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
