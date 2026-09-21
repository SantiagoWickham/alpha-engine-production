from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AuditValue:
    value: Any
    source: str
    asof: str | None
    status: str
    fallback: str = "none"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MarketSnapshot:
    ticker: str
    market_symbol: str
    retrieved_at: str
    currency: str | None = None
    exchange: str | None = None
    market_state: str | None = None
    fields: dict[str, AuditValue] = field(default_factory=dict)
    metrics: dict[str, AuditValue] = field(default_factory=dict)
    coverage: float = 0.0
    overall_status: str = "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "market_symbol": self.market_symbol,
            "retrieved_at": self.retrieved_at,
            "currency": self.currency,
            "exchange": self.exchange,
            "market_state": self.market_state,
            "coverage": self.coverage,
            "overall_status": self.overall_status,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
            "metrics": {k: v.to_dict() for k, v in self.metrics.items()},
        }
