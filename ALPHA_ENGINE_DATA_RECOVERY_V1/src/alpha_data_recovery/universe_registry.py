from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UniverseRecord:
    canonical_ticker: str
    asset_class: str
    motor: str
    sector: str
    benchmark: str
    market_symbol: str
    fundamentals_symbol: str
    sec_ticker: str
    country: str
    active: bool
    note: str


def load_universe(path: str | Path) -> list[UniverseRecord]:
    path = Path(path)
    out: list[UniverseRecord] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            ticker = (r.get("canonical_ticker") or "").strip().upper()
            if not ticker:
                continue
            out.append(
                UniverseRecord(
                    canonical_ticker=ticker,
                    asset_class=(r.get("asset_class") or "").strip(),
                    motor=(r.get("motor") or "").strip(),
                    sector=(r.get("sector") or "").strip(),
                    benchmark=(r.get("benchmark") or "").strip(),
                    market_symbol=(r.get("market_symbol") or ticker).strip(),
                    fundamentals_symbol=(r.get("fundamentals_symbol") or ticker).strip(),
                    sec_ticker=(r.get("sec_ticker") or "").strip(),
                    country=(r.get("country") or "").strip(),
                    active=(r.get("active") or "SI").strip().upper() != "NO",
                    note=(r.get("note") or "").strip(),
                )
            )
    return out
