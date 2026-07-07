from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

import pandas as pd

from backtesting.costs import TransactionCostModel
from backtesting.models import BacktestConfig, BacktestResult, DailyPortfolio, Signal
from backtesting.portfolio import Portfolio
from backtesting.strategies.base import Strategy


REQUIRED_COLUMNS = {"date", "symbol", "close"}


class BacktestEngine:
    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.cost_model = TransactionCostModel(
            fee_rate=config.fee_rate,
            slippage_rate=config.slippage_rate,
        )

    def run(self, data: pd.DataFrame, strategy: Strategy) -> BacktestResult:
        prepared_data = self._prepare_data(data)
        signals = strategy.generate_signals(prepared_data)
        prepared_signals = self._prepare_signals(signals)
        data_with_signals = prepared_data.merge(prepared_signals, on=["date", "symbol"], how="left")
        data_with_signals["signal"] = data_with_signals["signal"].fillna(0).astype(int)
        data_with_signals["reason"] = data_with_signals["reason"].fillna("missing_signal")

        all_trades = []
        daily_rows = []
        signal_rows = []

        for symbol, symbol_data in data_with_signals.groupby("symbol", sort=False):
            portfolio = Portfolio(
                initial_capital=self.config.initial_capital,
                max_exposure=self.config.max_exposure,
                cost_model=self.cost_model,
                allow_short=self.config.allow_short,
            )
            symbol_data = symbol_data.sort_values("date").reset_index(drop=True)
            symbol_data["executed_signal"] = symbol_data["signal"].shift(1).fillna(0).astype(int)
            symbol_data["execution_reason"] = symbol_data["reason"].shift(1).fillna("first_day_no_execution")

            for row in symbol_data.itertuples(index=False):
                requested_signal = int(row.executed_signal)
                if requested_signal < 0 and not self.config.allow_short:
                    requested_signal = 0

                trade = portfolio.rebalance_to_signal(
                    date=row.date,
                    symbol=symbol,
                    price=float(row.close),
                    signal=requested_signal,
                    reason=str(row.execution_reason),
                )
                if trade is not None:
                    all_trades.append(trade)

                equity = portfolio.equity(float(row.close))
                market_value = portfolio.market_value(float(row.close))
                daily_rows.append(
                    DailyPortfolio(
                        date=row.date,
                        symbol=symbol,
                        strategy_name=strategy.name,
                        cash=portfolio.cash,
                        position=portfolio.position,
                        close=float(row.close),
                        market_value=market_value,
                        equity=equity,
                        exposure=portfolio.exposure(float(row.close)),
                        signal=int(row.signal),
                        executed_signal=requested_signal,
                        run_at=self.config.run_at,
                    )
                )
                signal_rows.append(
                    Signal(
                        date=row.date,
                        symbol=symbol,
                        signal=int(row.signal),
                        reason=str(row.reason),
                    )
                )

        return BacktestResult(
            strategy_name=strategy.name,
            config=self.config,
            trades=all_trades,
            daily_portfolio=daily_rows,
            signals=signal_rows,
        )

    def run_many(self, data: pd.DataFrame, strategies: Iterable[Strategy]) -> list[BacktestResult]:
        return [self.run(data, strategy) for strategy in strategies]

    def result_to_frames(self, result: BacktestResult) -> dict[str, pd.DataFrame]:
        return {
            "trades": pd.DataFrame([asdict(trade) for trade in result.trades]),
            "daily_portfolio": pd.DataFrame([asdict(row) for row in result.daily_portfolio]),
            "signals": pd.DataFrame([asdict(signal) for signal in result.signals]),
            "metadata": pd.DataFrame(
                [
                    {
                        "strategy_name": result.strategy_name,
                        "initial_capital": result.config.initial_capital,
                        "max_exposure": result.config.max_exposure,
                        "fee_rate": result.config.fee_rate,
                        "slippage_rate": result.config.slippage_rate,
                        "allow_short": result.config.allow_short,
                        "run_at": result.config.run_at,
                        "parameters": result.config.parameters,
                    }
                ]
            ),
        }

    def _prepare_data(self, data: pd.DataFrame) -> pd.DataFrame:
        missing_columns = REQUIRED_COLUMNS - set(data.columns)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"Missing required columns: {missing}")

        prepared_data = data.copy()
        prepared_data["date"] = pd.to_datetime(prepared_data["date"]).dt.date
        prepared_data = prepared_data.sort_values(["symbol", "date"]).reset_index(drop=True)
        return prepared_data

    def _prepare_signals(self, signals: pd.DataFrame) -> pd.DataFrame:
        required_signal_columns = {"date", "symbol", "signal", "reason"}
        missing_columns = required_signal_columns - set(signals.columns)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"Missing signal columns: {missing}")

        prepared_signals = signals.copy()
        prepared_signals["date"] = pd.to_datetime(prepared_signals["date"]).dt.date
        prepared_signals["signal"] = prepared_signals["signal"].clip(lower=-1, upper=1).astype(int)
        if not self.config.allow_short:
            prepared_signals.loc[prepared_signals["signal"] < 0, "signal"] = 0
        return prepared_signals[["date", "symbol", "signal", "reason"]]
