"""미국(NYSE/NASDAQ) 데이터 어댑터 — yfinance 기반.

핵심 이슈
--------
yfinance의 `.info`(회사명/섹터/펀더멘털) 엔드포인트는 **데이터센터 IP(클라우드)에서
야후에게 자주 차단/레이트리밋** 된다. 반면 `yf.download`(주가)은 클라우드에서도 잘 된다.

그래서:
  • 유니버스(회사명/섹터/시총) + 펀더멘털 스냅샷 : 사전 생성한 정적 목록 us_universe.py
  • 일봉/실시간 시세 : yf.download (라이브, 클라우드 OK)
  • 로컬(Windows)에서는 .info 로 펀더멘털을 라이브로 갱신하고, 빠진 값만 정적 스냅샷으로 보강.

환경변수 QS_US_SOURCE=static|live 로 강제 지정 가능.
"""
from __future__ import annotations

import os
import platform
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .base import DataSource, ProgressCB
from .us_universe import US_UNIVERSE

_FUND_COLS = ["per", "pbr", "dividend_yield", "roe", "debt_to_equity", "profit_margin"]


def _prefer_live() -> bool:
    env = os.environ.get("QS_US_SOURCE", "").lower()
    if env == "static":
        return False
    if env == "live":
        return True
    return platform.system() == "Windows"   # 로컬만 라이브 .info, 클라우드는 정적


class USSource(DataSource):
    market = "US"
    currency = "$"
    price_decimals = 2

    def __init__(self) -> None:
        self._info_cache: dict[str, dict] = {}
        self._live = _prefer_live()
        # ticker -> (name, sector, cap, per, pbr, div, roe)
        self._static: dict[str, tuple] = {row[0]: tuple(row[1:]) for row in US_UNIVERSE}

    # ── yfinance .info (로컬 라이브용) ─────────────────────
    def _ensure_info(self, tickers: list[str], progress: ProgressCB = None) -> None:
        import yfinance as yf
        todo = [t for t in tickers if t not in self._info_cache]
        if not todo:
            return

        def fetch(t):
            try:
                return t, yf.Ticker(t).info
            except Exception:
                return t, {}

        done, n = 0, len(todo)
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(fetch, t) for t in todo]
            for f in as_completed(futs):
                t, info = f.result()
                self._info_cache[t] = info or {}
                done += 1
                if progress:
                    progress(done / n, t)

    @staticmethod
    def _extract_close(data: pd.DataFrame, tickers: list[str]) -> pd.DataFrame | None:
        if data is None or data.empty:
            return None
        if isinstance(data.columns, pd.MultiIndex):
            if "Close" in data.columns.get_level_values(0):
                return data["Close"]
            return None
        if "Close" in data.columns:
            df = data[["Close"]].copy()
            df.columns = [tickers[0]]
            return df
        return None

    @staticmethod
    def _norm_dividend(info: dict) -> float:
        dy = info.get("trailingAnnualDividendYield")
        if dy is None:
            dy = info.get("dividendYield")
        if dy is None:
            return np.nan
        return dy * 100.0 if dy < 1 else float(dy)

    # ── 인터페이스 구현 ─────────────────────────────────────
    def get_universe(self, limit: int) -> pd.DataFrame:
        items = US_UNIVERSE[:limit]   # 이미 시총 내림차순
        return pd.DataFrame(
            {"name": [r[1] for r in items],
             "sector": [r[2] for r in items],
             "market_cap": [float(r[3]) if r[3] else np.nan for r in items]},
            index=[r[0] for r in items],
        )

    def _fund_static(self, tickers: list[str]) -> pd.DataFrame:
        out = pd.DataFrame(index=tickers, columns=_FUND_COLS, dtype=float)
        for t in tickers:
            st = self._static.get(t)
            if st:   # (name, sector, cap, per, pbr, div, roe)
                out.loc[t, "per"] = st[3]
                out.loc[t, "pbr"] = st[4]
                out.loc[t, "dividend_yield"] = st[5]
                out.loc[t, "roe"] = st[6]
        return out.apply(pd.to_numeric, errors="coerce")

    def get_fundamentals(self, tickers: list[str], progress: ProgressCB = None) -> pd.DataFrame:
        if not self._live:
            if progress:
                progress(1.0, "정적")
            return self._fund_static(tickers)

        # 로컬: 라이브 .info + 빠진 값은 정적 스냅샷으로 보강
        self._ensure_info(tickers, progress)
        static = self._fund_static(tickers)
        out = pd.DataFrame(index=tickers, columns=_FUND_COLS, dtype=float)
        for t in tickers:
            info = self._info_cache.get(t, {})
            roe = info.get("returnOnEquity")
            pm = info.get("profitMargins")
            out.loc[t, "per"] = info.get("trailingPE")
            out.loc[t, "pbr"] = info.get("priceToBook")
            out.loc[t, "dividend_yield"] = self._norm_dividend(info)
            out.loc[t, "roe"] = roe * 100.0 if isinstance(roe, (int, float)) else np.nan
            out.loc[t, "debt_to_equity"] = info.get("debtToEquity")
            out.loc[t, "profit_margin"] = pm * 100.0 if isinstance(pm, (int, float)) else np.nan
        out = out.apply(pd.to_numeric, errors="coerce")
        # .info가 비어있던 칼럼을 정적값으로 채움
        return out.fillna(static)

    def get_price_history(self, tickers: list[str], days: int,
                          progress: ProgressCB = None) -> pd.DataFrame:
        import yfinance as yf
        start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
        try:
            data = yf.download(tickers, start=start, auto_adjust=True,
                               progress=False, threads=True)
        except Exception:
            return pd.DataFrame()
        close = self._extract_close(data, tickers)
        if progress:
            progress(1.0, "일봉")
        if close is None:
            return pd.DataFrame()
        return close.sort_index()

    def get_quotes(self, tickers: list[str]) -> pd.DataFrame:
        import yfinance as yf
        out = pd.DataFrame(index=tickers, columns=["price", "change_pct"], dtype=float)
        prev_close = day_price = fresh = None
        try:
            daily = self._extract_close(
                yf.download(tickers, period="5d", interval="1d",
                            progress=False, threads=True, auto_adjust=False), tickers)
            if daily is not None and not daily.dropna(how="all").empty:
                daily = daily.ffill()
                day_price = daily.iloc[-1]
                prev_close = daily.iloc[-2] if len(daily) >= 2 else daily.iloc[-1]
        except Exception:
            pass
        try:
            intraday = self._extract_close(
                yf.download(tickers, period="1d", interval="1m",
                            progress=False, threads=True, auto_adjust=False), tickers)
            if intraday is not None and not intraday.dropna(how="all").empty:
                fresh = intraday.ffill().iloc[-1]
        except Exception:
            pass
        if day_price is None and fresh is None:
            return out
        price = fresh.combine_first(day_price) if (fresh is not None and day_price is not None) \
            else (fresh if fresh is not None else day_price)
        out["price"] = price.reindex(tickers)
        if prev_close is not None:
            out["change_pct"] = ((price / prev_close - 1.0) * 100.0).reindex(tickers)
        return out
