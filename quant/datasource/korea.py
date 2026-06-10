"""한국(KOSPI/KOSDAQ) 데이터 어댑터.

설계 메모
--------
pykrx는 KRX 스크래핑이라 환경에 따라 자주 차단된다(빈 응답). 그래서 이 어댑터는
의존하지 않고, 안정적으로 동작하는 두 소스만 사용한다.

- 유니버스/시총/현재가/등락률 : FinanceDataReader.StockListing('KRX')  (단일 호출)
- 일봉 히스토리              : FinanceDataReader.DataReader            (종목별 루프, 캐시)
- 펀더멘털(PER/PBR/배당/ROE) : 네이버 모바일 API integration          (스레드풀 병렬)
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

from .base import DataSource, ProgressCB

_NAVER_URL = "https://m.stock.naver.com/api/stock/{code}/integration"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Referer": "https://m.stock.naver.com/",
}


def _num(s) -> float:
    """'26.03배' → 26.03, '0.52%' → 0.52, '12,372원' → 12372. 숫자 없으면 NaN."""
    if s is None:
        return np.nan
    m = re.search(r"-?\d[\d,]*(\.\d+)?", str(s))
    return float(m.group().replace(",", "")) if m else np.nan


class KoreaSource(DataSource):
    market = "KR"
    currency = "₩"
    price_decimals = 0

    def __init__(self) -> None:
        self._listing: pd.DataFrame | None = None     # FDR StockListing 캐시(정규화)
        self._fund_cache: dict[str, dict] = {}        # 티커 → 네이버 펀더멘털 캐시
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    # ── FDR 상장목록(정규화) ───────────────────────────────
    def _get_listing(self) -> pd.DataFrame:
        if self._listing is not None:
            return self._listing
        import FinanceDataReader as fdr
        lst = fdr.StockListing("KRX")
        cols = {str(c).lower(): c for c in lst.columns}

        def pick(*names):
            return next((cols[n] for n in names if n in cols), None)

        code_c = pick("code", "symbol", "ticker")
        name_c = pick("name")
        mkt_c = pick("market")
        cap_c = pick("marcap", "시가총액", "marketcap")
        close_c = pick("close", "종가")
        chg_c = pick("chagesratio", "changesratio", "changeratio", "등락률")
        if not code_c or not name_c:
            raise RuntimeError("FDR StockListing 형식을 해석할 수 없습니다.")

        df = pd.DataFrame({
            "code": lst[code_c].astype(str).str.zfill(6),
            "name": lst[name_c],
            "market": lst[mkt_c] if mkt_c else "",
            "market_cap": pd.to_numeric(lst[cap_c], errors="coerce") if cap_c else np.nan,
            "close": pd.to_numeric(lst[close_c], errors="coerce") if close_c else np.nan,
            "change_pct": pd.to_numeric(lst[chg_c], errors="coerce") if chg_c else np.nan,
        }).set_index("code")
        self._listing = df
        return df

    # ── 네이버 펀더멘털 ─────────────────────────────────────
    def _fetch_one(self, code: str) -> dict:
        try:
            r = self._session.get(_NAVER_URL.format(code=code), timeout=8)
            info = {d.get("code"): d.get("value")
                    for d in (r.json().get("totalInfos") or [])}
            per = _num(info.get("per"))
            pbr = _num(info.get("pbr"))
            eps = _num(info.get("eps"))
            bps = _num(info.get("bps"))
            roe = (eps / bps * 100.0) if (eps and bps and bps != 0) else np.nan
            return {
                "per": per if per > 0 else np.nan,
                "pbr": pbr if pbr > 0 else np.nan,
                "dividend_yield": _num(info.get("dividendYieldRatio")),
                "roe": roe,
                "debt_to_equity": np.nan,
                "profit_margin": np.nan,
            }
        except Exception:
            return {"per": np.nan, "pbr": np.nan, "dividend_yield": np.nan,
                    "roe": np.nan, "debt_to_equity": np.nan, "profit_margin": np.nan}

    def _ensure_fundamentals(self, tickers: list[str], progress: ProgressCB = None) -> None:
        todo = [t for t in tickers if t not in self._fund_cache]
        if not todo:
            return
        done, n = 0, len(todo)
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(self._fetch_one, t): t for t in todo}
            for f in as_completed(futs):
                t = futs[f]
                self._fund_cache[t] = f.result()
                done += 1
                if progress:
                    progress(done / n, t)

    # ── 인터페이스 구현 ─────────────────────────────────────
    def get_universe(self, limit: int) -> pd.DataFrame:
        lst = self._get_listing()
        df = lst[lst["market"].isin(["KOSPI", "KOSDAQ"])] if lst["market"].notna().any() else lst
        df = df[df["market_cap"] > 0].sort_values("market_cap", ascending=False).head(limit)
        return pd.DataFrame({
            "name": df["name"],
            "sector": df["market"],   # KR은 GICS 섹터가 없어 시장(KOSPI/KOSDAQ)으로 대체
            "market_cap": df["market_cap"],
        }, index=df.index)

    def get_fundamentals(self, tickers: list[str], progress: ProgressCB = None) -> pd.DataFrame:
        self._ensure_fundamentals(tickers, progress)
        rows = [self._fund_cache.get(t, {}) for t in tickers]
        return pd.DataFrame(rows, index=tickers,
                            columns=["per", "pbr", "dividend_yield", "roe",
                                     "debt_to_equity", "profit_margin"])

    def get_price_history(self, tickers: list[str], days: int,
                          progress: ProgressCB = None) -> pd.DataFrame:
        import FinanceDataReader as fdr
        start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
        series: dict[str, pd.Series] = {}
        n = max(len(tickers), 1)
        for i, t in enumerate(tickers):
            try:
                d = fdr.DataReader(t, start)
                if not d.empty and "Close" in d:
                    series[t] = d["Close"]
            except Exception:
                pass
            if progress:
                progress((i + 1) / n, t)
        if not series:
            return pd.DataFrame()
        return pd.DataFrame(series).sort_index()

    def get_quotes(self, tickers: list[str]) -> pd.DataFrame:
        """FDR 상장목록 스냅샷에서 현재가·등락률을 추출(장중 지연 반영)."""
        out = pd.DataFrame(index=tickers, columns=["price", "change_pct"], dtype=float)
        try:
            # 시세는 매 폴링마다 새로 받아야 하므로 캐시를 비우고 재조회
            self._listing = None
            lst = self._get_listing()
        except Exception:
            return out
        sub = lst.reindex(tickers)
        out["price"] = sub["close"]
        out["change_pct"] = sub["change_pct"]
        return out
