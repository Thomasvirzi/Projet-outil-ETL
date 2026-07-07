from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class BacktestConfig:
    strategy_name: str
    initial_capital: float = 100_000.0
    max_exposure: float = 1.0
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    allow_short: bool = False
    run_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Signal:
    date: Any
    symbol: str
    signal: int
    reason: str


@dataclass(frozen=True)
class Trade:
    date: Any
    symbol: str
    action: str
    quantity: float
    price: float
    gross_amount: float
    fee: float
    slippage: float
    cash_after: float
    position_after: float
    reason: str


@dataclass(frozen=True)
class DailyPortfolio:
    date: Any
    symbol: str
    strategy_name: str
    cash: float
    position: float
    close: float
    market_value: float
    equity: float
    exposure: float
    signal: int
    executed_signal: int
    run_at: datetime


@dataclass(frozen=True)
class BacktestResult:
    strategy_name: str
    config: BacktestConfig
    trades: list[Trade]
    daily_portfolio: list[DailyPortfolio]
    signals: list[Signal]

