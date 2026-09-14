from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class InformationStamp:
    observation_time: datetime
    available_at: datetime
    ingested_at: datetime

    def validate(self) -> None:
        if self.available_at < self.observation_time:
            raise ValueError("available_at cannot precede observation_time")
        if self.ingested_at < self.available_at:
            raise ValueError("ingested_at cannot precede available_at")


@dataclass(frozen=True)
class DecisionStamp:
    decision_time: datetime
    execution_earliest: datetime

    def validate_against(self, info: InformationStamp) -> None:
        info.validate()
        if info.available_at > self.decision_time:
            raise ValueError("future information used by decision")
        if self.execution_earliest < self.decision_time:
            raise ValueError("execution cannot precede decision")
