"""통합(한국+미국) 데이터 소스.

KoreaSource + USSource 를 감싸, 두 시장 종목을 하나의 유니버스로 합친다.
팩터 z-score는 합쳐진 유니버스 전체에 대해 계산되므로 **국가 교차 랭킹**이 된다
(모멘텀·변동성·PER·ROE 등은 모두 비율/표준화 값이라 통화와 무관하게 비교 가능).

종목 구분: 한국 코드는 6자리 숫자, 미국 티커는 영문자 → ticker.isdigit() 로 라우팅.
시가총액은 통화가 달라(₩ vs $) 시장별로 각자 상위 N/2씩 뽑은 뒤 합친다.
"""
from __future__ import annotations

import pandas as pd

from .base import DataSource, ProgressCB
from .korea import KoreaSource
from .us import USSource

_FUND_COLS = ["per", "pbr", "dividend_yield", "roe", "debt_to_equity", "profit_margin"]


class CombinedSource(DataSource):
    market = "BOTH"
    currency = ""          # 혼합 통화 — 행별로 ₩/$ 표시
    price_decimals = 2

    def __init__(self) -> None:
        self._kr = KoreaSource()
        self._us = USSource()

    @staticmethod
    def _is_kr(ticker: str) -> bool:
        return str(ticker).isdigit()

    def _split(self, tickers: list[str]) -> tuple[list[str], list[str]]:
        kr = [t for t in tickers if self._is_kr(t)]
        us = [t for t in tickers if not self._is_kr(t)]
        return kr, us

    def get_universe(self, limit: int) -> pd.DataFrame:
        n_kr = max(limit // 2, 1)
        n_us = max(limit - n_kr, 1)
        kr = self._kr.get_universe(n_kr).copy()
        us = self._us.get_universe(n_us).copy()
        kr["mkt"] = "KR"
        us["mkt"] = "US"
        return pd.concat([kr, us])

    def get_price_history(self, tickers: list[str], days: int,
                          progress: ProgressCB = None) -> pd.DataFrame:
        kr, us = self._split(tickers)
        frames = []
        if kr:
            frames.append(self._kr.get_price_history(kr, days))
        if us:
            frames.append(self._us.get_price_history(us, days))
        frames = [f for f in frames if f is not None and not f.empty]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, axis=1).sort_index()

    def get_fundamentals(self, tickers: list[str], progress: ProgressCB = None) -> pd.DataFrame:
        kr, us = self._split(tickers)
        parts = []
        if kr:
            parts.append(self._kr.get_fundamentals(kr))
        if us:
            parts.append(self._us.get_fundamentals(us))
        if not parts:
            return pd.DataFrame(index=tickers, columns=_FUND_COLS, dtype=float)
        return pd.concat(parts).reindex(tickers)

    def get_quotes(self, tickers: list[str]) -> pd.DataFrame:
        kr, us = self._split(tickers)
        parts = []
        if kr:
            parts.append(self._kr.get_quotes(kr))
        if us:
            parts.append(self._us.get_quotes(us))
        if not parts:
            return pd.DataFrame(index=tickers, columns=["price", "change_pct"], dtype=float)
        return pd.concat(parts).reindex(tickers)
