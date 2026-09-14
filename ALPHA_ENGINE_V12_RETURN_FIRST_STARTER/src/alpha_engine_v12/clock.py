from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TradeAction(str, Enum):
    HOLD = "HOLD"
    REOPTIMIZE = "REOPTIMIZE"


@dataclass(frozen=True)
class DecisionTrigger:
    expected_incremental_return: float
    estimated_total_cost: float
    uncertainty_buffer: float
    minimum_edge: float

    @property
    def net_edge(self) -> float:
        return self.expected_incremental_return - self.estimated_total_cost - self.uncertainty_buffer

    def action(self) -> TradeAction:
        return TradeAction.REOPTIMIZE if self.net_edge > self.minimum_edge else TradeAction.HOLD
