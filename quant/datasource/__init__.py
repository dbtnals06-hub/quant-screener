"""데이터 소스 팩토리 — 시장 코드로 적절한 어댑터를 생성한다."""
from __future__ import annotations

import config
from .base import DataSource
from .korea import KoreaSource
from .us import USSource


def get_source(market: str) -> DataSource:
    if market == config.MARKET_KR:
        return KoreaSource()
    if market == config.MARKET_US:
        return USSource()
    raise ValueError(f"알 수 없는 시장 코드: {market}")


__all__ = ["DataSource", "KoreaSource", "USSource", "get_source"]
