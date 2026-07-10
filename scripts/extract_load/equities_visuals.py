"""Headless matplotlib charts for the equities pipeline.

All figures are rendered with the non-interactive Agg backend and saved as PNG — no display
server is required, so this runs the same way in a CI job or a laptop without a GUI. Each
function returns the written path, or None when there is not enough data to draw anything
(so callers can skip a chart without crashing the pipeline).
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

LOGGER = logging.getLogger(__name__)


def _save_figure(fig: plt.Figure, output_dir: Path, filename: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    LOGGER.info("Graphique enregistré : %s", path)
    return path


def plot_equity_vs_buy_hold(daily_curves: pd.DataFrame, symbol: str, output_dir: Path) -> Path | None:
    """daily_curves columns: date, symbol, series_name, series_type, equity."""
    subset = daily_curves[daily_curves["symbol"] == symbol]
    if subset.empty:
        return None

    fig, ax = plt.subplots(figsize=(10, 5))
    for series_name, rows in subset.groupby("series_name"):
        rows = rows.sort_values("date")
        ax.plot(rows["date"], rows["equity"], label=series_name)
    ax.set_title(f"{symbol} — Stratégie vs Buy & Hold")
    ax.set_xlabel("Date")
    ax.set_ylabel("Valeur du portefeuille")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    return _save_figure(fig, output_dir, f"equity_vs_buy_hold_{symbol.replace('.', '_')}.png")


def plot_drawdown(daily_curves: pd.DataFrame, symbol: str, output_dir: Path) -> Path | None:
    subset = daily_curves[daily_curves["symbol"] == symbol]
    if subset.empty:
        return None

    fig, ax = plt.subplots(figsize=(10, 4))
    for series_name, rows in subset.groupby("series_name"):
        rows = rows.sort_values("date")
        running_max = rows["equity"].cummax()
        drawdown = rows["equity"] / running_max - 1
        ax.plot(rows["date"], drawdown, label=series_name)
    ax.set_title(f"{symbol} — Drawdown")
    ax.set_ylabel("Drawdown")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    return _save_figure(fig, output_dir, f"drawdown_{symbol.replace('.', '_')}.png")


def plot_cumulative_returns_by_ticker(price_panel: pd.DataFrame, output_dir: Path) -> Path | None:
    """price_panel: wide frame, index=date, one column of adjusted close per ticker."""
    if price_panel.empty:
        return None

    normalized = price_panel.divide(price_panel.iloc[0]).multiply(100)
    fig, ax = plt.subplots(figsize=(11, 6))
    for column in normalized.columns:
        ax.plot(normalized.index, normalized[column], label=column, linewidth=1)
    ax.set_title("Rendements cumulés par action (base 100)")
    ax.set_ylabel("Indice (base 100)")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    return _save_figure(fig, output_dir, "cumulative_returns_by_ticker.png")


def plot_portfolio_performance(portfolio_daily: pd.DataFrame, output_dir: Path) -> Path | None:
    """portfolio_daily columns: date, index_level, drawdown."""
    required = {"date", "index_level", "drawdown"}
    if portfolio_daily.empty or not required.issubset(portfolio_daily.columns):
        return None

    ordered = portfolio_daily.sort_values("date")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    ax1.plot(ordered["date"], ordered["index_level"], color="tab:blue")
    ax1.set_title("Portefeuille equal-weight — valeur de l'indice")
    ax1.grid(alpha=0.3)
    ax2.fill_between(ordered["date"], ordered["drawdown"], 0, color="tab:red", alpha=0.4)
    ax2.set_title("Drawdown du portefeuille")
    ax2.grid(alpha=0.3)
    fig.autofmt_xdate()
    return _save_figure(fig, output_dir, "portfolio_performance.png")


def plot_correlation_heatmap(returns: pd.DataFrame, output_dir: Path) -> Path | None:
    """returns: wide frame of daily returns, one column per ticker."""
    if returns.empty or returns.shape[1] < 2:
        return None

    correlation = returns.corr()
    fig, ax = plt.subplots(figsize=(9, 8))
    image = ax.imshow(correlation.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(correlation.columns)))
    ax.set_xticklabels(correlation.columns, rotation=90, fontsize=7)
    ax.set_yticks(range(len(correlation.columns)))
    ax.set_yticklabels(correlation.columns, fontsize=7)
    fig.colorbar(image, ax=ax, label="Corrélation")
    ax.set_title("Corrélation des rendements quotidiens")
    return _save_figure(fig, output_dir, "correlation_heatmap.png")


def plot_risk_return_scatter(summary: pd.DataFrame, output_dir: Path) -> Path | None:
    """summary columns: symbol, annualized_return, annualized_volatility, max_drawdown."""
    required = {"symbol", "annualized_return", "annualized_volatility", "max_drawdown"}
    if summary.empty or not required.issubset(summary.columns):
        return None

    fig, ax = plt.subplots(figsize=(9, 7))
    sizes = 200 * (1 + summary["max_drawdown"].abs())
    scatter = ax.scatter(
        summary["annualized_volatility"],
        summary["annualized_return"],
        s=sizes,
        c=summary["max_drawdown"],
        cmap="RdYlGn",
        alpha=0.75,
        edgecolors="black",
    )
    for _, row in summary.iterrows():
        ax.annotate(str(row["symbol"]), (row["annualized_volatility"], row["annualized_return"]), fontsize=7)
    fig.colorbar(scatter, ax=ax, label="Max drawdown")
    ax.set_xlabel("Volatilité annualisée")
    ax.set_ylabel("Rendement annualisé")
    ax.set_title("Rendement vs volatilité vs max drawdown")
    ax.grid(alpha=0.3)
    return _save_figure(fig, output_dir, "risk_return_scatter.png")


def plot_strategy_ranking(
    summary: pd.DataFrame,
    output_dir: Path,
    metric: str = "sharpe_ratio",
) -> Path | None:
    if summary.empty or metric not in summary.columns or "symbol" not in summary.columns:
        return None

    ranked = summary.sort_values(metric, ascending=False)
    fig, ax = plt.subplots(figsize=(9, max(4, 0.35 * len(ranked))))
    colors = ["tab:green" if value >= 0 else "tab:red" for value in ranked[metric]]
    ax.barh(ranked["symbol"], ranked[metric], color=colors)
    ax.invert_yaxis()
    ax.set_xlabel(metric)
    ax.set_title(f"Classement des actions par {metric}")
    ax.grid(alpha=0.3, axis="x")
    return _save_figure(fig, output_dir, f"ranking_{metric}.png")
