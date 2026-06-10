"""데이터 소스 공통 인터페이스.

한국·미국 어댑터가 동일한 시그니처를 구현하므로, 상위 코드는 시장을 몰라도 된다.
모든 메서드는 네트워크 실패 시 예외를 던지기보다 '가능한 만큼' 반환하도록 구현하고,
호출부(app.py)에서 결측을 경고로 표시한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional

import pandas as pd

# 진행률 콜백: fraction(0~1), label 을 받는다(없으면 None).
# 주의: 이 줄은 모듈 로드 시 '실제로' 평가되므로 PEP604(`X | None`) 대신
#       모든 파이썬 버전에서 안전한 Optional[...] 을 쓴다.
ProgressCB = Optional[Callable[[float, str], None]]


class DataSource(ABC):
    market: str          # "KR" / "US"
    currency: str        # "₩" / "$"
    price_decimals: int  # 표시 소수 자리

    @abstractmethod
    def get_universe(self, limit: int) -> pd.DataFrame:
        """시가총액 상위 종목 유니버스.

        반환: index=티커, columns=['name','sector','market_cap']
        """

    @abstractmethod
    def get_price_history(self, tickers: list[str], days: int,
                          progress: ProgressCB = None) -> pd.DataFrame:
        """일봉 수정종가. 반환: wide DataFrame(index=날짜, columns=티커)."""

    @abstractmethod
    def get_fundamentals(self, tickers: list[str],
                         progress: ProgressCB = None) -> pd.DataFrame:
        """펀더멘털.

        반환 index=티커, 표준 컬럼(없으면 NaN):
            per, pbr, dividend_yield(%), roe(%), debt_to_equity, profit_margin(%)
        """

    @abstractmethod
    def get_quotes(self, tickers: list[str]) -> pd.DataFrame:
        """근실시간 시세 스냅샷.

        반환 index=티커, columns=['price','change_pct']
        """
