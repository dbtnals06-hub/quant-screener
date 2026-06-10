"""미국(NYSE/NASDAQ) 데이터 어댑터 — yfinance 기반.

- 유니버스/펀더멘털/시총/섹터 : yf.Ticker(t).info (티커당 1회, 스레드풀로 병렬 + 인스턴스 캐시)
- 일봉 히스토리 : yf.download (단일 배치 호출)
- 근실시간 스냅샷 : 분봉 최신가 + 일봉 전일종가로 등락률 산출
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .base import DataSource, ProgressCB
from .universe import US_LARGE_CAP_FALLBACK


class USSource(DataSource):
    market = "US"
    currency = "$"
    price_decimals = 2

    def __init__(self) -> None:
        # 티커 → info dict 캐시. get_universe/get_fundamentals가 공유해 중복 호출 방지.
        self._info_cache: dict[str, dict] = {}

    # ── 내부 유틸 ───────────────────────────────────────────
    def _candidates(self, limit: int) -> list[str]:
        """후보 티커: 대형주 폴백 목록을 기본으로, 가능하면 S&P500으로 확장."""
        base = list(US_LARGE_CAP_FALLBACK)
        seen = set(base)
        try:  # 위키피디아 S&P500 — 오프라인/차단 시 조용히 건너뜀
            tables = pd.read_html(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
            wiki = tables[0]
            col = "Symbol" if "Symbol" in wiki.columns else wiki.columns[0]
            for s in wiki[col].astype(str):
                s = s.strip().replace(".", "-")  # BRK.B → BRK-B (yfinance 규격)
                if s and s not in seen:
                    base.append(s)
                    seen.add(s)
        except Exception:
            pass
        return base[: max(limit, 1)]

    def _ensure_info(self, tickers: list[str], progress: ProgressCB = None) -> None:
        import yfinance as yf
        todo = [t for t in tickers if t not in self._info_cache]
        if not todo:
            if progress:
                progress(1.0, "")
            return

        def fetch(t: str):
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

    def _extract_close(self, data: pd.DataFrame, tickers: list[str]) -> pd.DataFrame | None:
        """yf.download 결과에서 종가만 wide(index=날짜, cols=티커)로 추출."""
        if data is None or data.empty:
            return None
        if isinstance(data.columns, pd.MultiIndex):
            if "Close" in data.columns.get_level_values(0):
                return data["Close"]
            return None
        if "Close" in data.columns:  # 단일 티커 → 평면 컬럼
            df = data[["Close"]].copy()
            df.columns = [tickers[0]]
            return df
        return None

    @staticmethod
    def _norm_dividend(info: dict) -> float:
        """배당수익률을 %로 정규화. trailingAnnualDividendYield(분수) 우선."""
        dy = info.get("trailingAnnualDividendYield")
        if dy is None:
            dy = info.get("dividendYield")
        if dy is None:
            return np.nan
        return dy * 100.0 if dy < 1 else float(dy)

    # ── 인터페이스 구현 ─────────────────────────────────────
    def get_universe(self, limit: int) -> pd.DataFrame:
        cands = self._candidates(limit)
        self._ensure_info(cands)
        rows = []
        for t in cands:
            info = self._info_cache.get(t, {})
            rows.append((
                t,
                info.get("longName") or info.get("shortName") or t,
                info.get("sector") or "",
                info.get("marketCap"),
            ))
        df = pd.DataFrame(rows, columns=["ticker", "name", "sector", "market_cap"]).set_index("ticker")
        df = df.sort_values("market_cap", ascending=False, na_position="last").head(limit)
        return df

    def get_fundamentals(self, tickers: list[str], progress: ProgressCB = None) -> pd.DataFrame:
        self._ensure_info(tickers, progress)
        out = pd.DataFrame(index=tickers,
                           columns=["per", "pbr", "dividend_yield", "roe",
                                    "debt_to_equity", "profit_margin"], dtype=float)
        for t in tickers:
            info = self._info_cache.get(t, {})
            roe = info.get("returnOnEquity")
            pm = info.get("profitMargins")
            out.loc[t, "per"] = info.get("trailingPE")
            out.loc[t, "pbr"] = info.get("priceToBook")
            out.loc[t, "dividend_yield"] = self._norm_dividend(info)
            out.loc[t, "roe"] = roe * 100.0 if isinstance(roe, (int, float)) else np.nan
            out.loc[t, "debt_to_equity"] = info.get("debtToEquity")  # 이미 비율(%)
            out.loc[t, "profit_margin"] = pm * 100.0 if isinstance(pm, (int, float)) else np.nan
        return out.apply(pd.to_numeric, errors="coerce")

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

        # 1) 일봉(최근 5거래일)으로 전일종가 대비 등락률 산출
        prev_close = day_price = None
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

        # 2) 분봉 최신가로 현재가 신선도 향상(가능할 때만)
        fresh = None
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
