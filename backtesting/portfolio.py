from __future__ import annotations

from backtesting.costs import TransactionCostModel
from backtesting.models import Trade


class Portfolio:
    def __init__(
        self,
        *,
        initial_capital: float,
        max_exposure: float,
        cost_model: TransactionCostModel,
        allow_short: bool = False,
    ) -> None:
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if not 0 <= max_exposure <= 1:
            raise ValueError("max_exposure must be between 0 and 1")

        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.position = 0.0
        self.max_exposure = max_exposure
        self.cost_model = cost_model
        self.allow_short = allow_short

    def market_value(self, price: float) -> float:
        return self.position * price

    def equity(self, price: float) -> float:
        return self.cash + self.market_value(price)

    def exposure(self, price: float) -> float:
        equity = self.equity(price)
        if equity == 0:
            return 0.0
        return abs(self.market_value(price)) / equity

    def rebalance_to_signal(self, *, date, symbol: str, price: float, signal: int, reason: str) -> Trade | None:
        if signal < 0 and not self.allow_short:
            signal = 0

        target_value = self.equity(price) * self.max_exposure * signal
        target_position = target_value / price if price > 0 else 0.0
        quantity_delta = target_position - self.position

        if abs(quantity_delta) < 1e-12:
            return None

        side = "buy" if quantity_delta > 0 else "sell"
        execution_price = self.cost_model.execution_price(price, side)
        gross_amount = quantity_delta * execution_price
        fee = self.cost_model.fee(gross_amount)
        slippage = self.cost_model.slippage(quantity_delta * price)

        if side == "buy":
            total_cost = gross_amount + fee
            if total_cost > self.cash:
                affordable_quantity = self.cash / (execution_price * (1 + self.cost_model.fee_rate))
                quantity_delta = max(0.0, affordable_quantity)
                gross_amount = quantity_delta * execution_price
                fee = self.cost_model.fee(gross_amount)
                slippage = self.cost_model.slippage(quantity_delta * price)
                if quantity_delta == 0:
                    return None

        self.cash -= gross_amount + fee
        self.position += quantity_delta

        if not self.allow_short and self.position < 0:
            self.cash += self.position * execution_price
            self.position = 0.0

        return Trade(
            date=date,
            symbol=symbol,
            action=side,
            quantity=abs(quantity_delta),
            price=execution_price,
            gross_amount=abs(gross_amount),
            fee=fee,
            slippage=slippage,
            cash_after=self.cash,
            position_after=self.position,
            reason=reason,
        )

