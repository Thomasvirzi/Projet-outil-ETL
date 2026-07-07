from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransactionCostModel:
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005

    def fee(self, gross_amount: float) -> float:
        return abs(gross_amount) * self.fee_rate

    def slippage(self, gross_amount: float) -> float:
        return abs(gross_amount) * self.slippage_rate

    def execution_price(self, price: float, side: str) -> float:
        if side == "buy":
            return price * (1 + self.slippage_rate)
        if side == "sell":
            return price * (1 - self.slippage_rate)
        raise ValueError(f"Unsupported side: {side}")

