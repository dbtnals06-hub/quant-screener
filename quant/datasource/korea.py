"""한국(KOSPI/KOSDAQ) 데이터 어댑터 — 이중 경로.

환경에 따라 자동으로 최적 소스를 고른다.

  • 로컬(국내 IP, Windows): FinanceDataReader + 네이버 모바일 API
        → 정확한 PER/PBR/배당/ROE, 장중 시세. (KRX/네이버가 국내에서만 열림)

  • 클라우드(해외 IP, 비-Windows): yfinance(.KS/.KQ) + 네이버(되면) 폴백
        → KRX/네이버가 해외 IP를 차단하므로, 글로벌하게 열리는 야후로 한국 종목을 받는다.
          유니버스는 사전 생성한 정적 목록(kr_universe.py)을 사용한다.
          단, 야후는 한국 종목 PER/PBR을 잘 안 줘서 가치 팩터는 약해질 수 있다(모멘텀·저변동·ROE는 정상).

환경변수 QS_KR_SOURCE=yf|local 로 강제 지정 가능.
"""
from __future__ import annotations

import os
import platform
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

from .base import DataSource, ProgressCB
from .kr_universe import KR_UNIVERSE

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


def _prefer_local() -> bool:
    """국내 전용 소스(FDR+네이버)를 우선할지 여부."""
    env = os.environ.get("QS_KR_SOURCE", "").lower()
    if env == "yf":
        return False
    if env in ("local", "fdr", "naver"):
        return True
    # 기본: Windows(국내 사용자 PC로 가정)면 로컬 소스, 그 외(리눅스 클라우드)면 야후
    return platform.system() == "Windows"


class KoreaSource(DataSource):
    market = "KR"
    currency = "₩"
    price_decimals = 0

    def __init__(self) -> None:
        self._local = _prefer_local()
        self._listing: pd.DataFrame | None = None      # FDR 상장목록 캐시
        self._fund_cache: dict[str, dict] = {}         # 네이버 펀더멘털 캐시
        self._info_cache: dict[str, dict] = {}         # yfinance info 캐시
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        # 정적 유니버스: code -> (name, market, cap, yahoo_ticker, sector)
        self._static: dict[str, tuple] = {}
        self._sector_of: dict[str, str] = {}
        for code, name, mkt, cap, sector in KR_UNIVERSE:
            suffix = ".KS" if mkt == "KOSPI" else ".KQ"
            self._static[code] = (name, mkt, cap, code + suffix, sector)
            self._sector_of[code] = sector or mkt

    def _yahoo(self, code: str) -> str:
        rec = self._static.get(code)
        return rec[3] if rec else f"{code}.KS"

    # ════════ 로컬 경로: FinanceDataReader + 네이버 ════════
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

    def _universe_fdr(self, limit: int) -> pd.DataFrame:
        lst = self._get_listing()
        df = lst[lst["market"].isin(["KOSPI", "KOSDAQ"])] if lst["market"].notna().any() else lst
        df = df[df["market_cap"] > 0].sort_values("market_cap", ascending=False).head(limit)
        # 섹터: 정적 GICS 매핑 우선, 없으면 시장(KOSPI/KOSDAQ)
        sectors = [self._sector_of.get(code, mkt)
                   for code, mkt in zip(df.index, df["market"])]
        return pd.DataFrame({"name": df["name"], "sector": sectors,
                             "market_cap": df["market_cap"]}, index=df.index)

    def _quotes_fdr(self, tickers: list[str]) -> pd.DataFrame:
        out = pd.DataFrame(index=tickers, columns=["price", "change_pct"], dtype=float)
        self._listing = None  # 시세는 매번 새로
        lst = self._get_listing()
        sub = lst.reindex(tickers)
        out["price"] = sub["close"]
        out["change_pct"] = sub["change_pct"]
        return out

    def _prices_fdr(self, tickers: list[str], days: int, progress: ProgressCB) -> pd.DataFrame:
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
        return pd.DataFrame(series).sort_index() if series else pd.DataFrame()

    # 네이버 펀더멘털
    def _fetch_naver(self, code: str) -> dict:
        try:
            r = self._session.get(_NAVER_URL.format(code=code), timeout=8)
            info = {d.get("code"): d.get("value")
                    for d in (r.json().get("totalInfos") or [])}
            per, pbr = _num(info.get("per")), _num(info.get("pbr"))
            eps, bps = _num(info.get("eps")), _num(info.get("bps"))
            roe = (eps / bps * 100.0) if (eps and bps and bps != 0) else np.nan
            return {"per": per if per > 0 else np.nan,
                    "pbr": pbr if pbr > 0 else np.nan,
                    "dividend_yield": _num(info.get("dividendYieldRatio")),
                    "roe": roe, "debt_to_equity": np.nan, "profit_margin": np.nan}
        except Exception:
            return {}

    def _ensure_naver(self, tickers: list[str], progress: ProgressCB = None) -> None:
        todo = [t for t in tickers if t not in self._fund_cache]
        if not todo:
            return
        done, n = 0, len(todo)
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(self._fetch_naver, t): t for t in todo}
            for f in as_completed(futs):
                self._fund_cache[futs[f]] = f.result()
                done += 1
                if progress:
                    progress(done / n, futs[f])

    # ════════ 클라우드 경로: yfinance(.KS/.KQ) ════════
    def _ensure_info(self, codes: list[str], progress: ProgressCB = None) -> None:
        import yfinance as yf
        todo = [c for c in codes if c not in self._info_cache]
        if not todo:
            return

        def fetch(c):
            try:
                return c, yf.Ticker(self._yahoo(c)).info
            except Exception:
                return c, {}

        done, n = 0, len(todo)
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(fetch, c) for c in todo]
            for f in as_completed(futs):
                c, info = f.result()
                self._info_cache[c] = info or {}
                done += 1
                if progress:
                    progress(done / n, c)

    @staticmethod
    def _extract_close(data: pd.DataFrame, ytickers: list[str]) -> pd.DataFrame | None:
        if data is None or data.empty:
            return None
        if isinstance(data.columns, pd.MultiIndex):
            if "Close" in data.columns.get_level_values(0):
                return data["Close"]
            return None
        if "Close" in data.columns:
            df = data[["Close"]].copy()
            df.columns = [ytickers[0]]
            return df
        return None

    def _universe_yf(self, limit: int) -> pd.DataFrame:
        items = KR_UNIVERSE[:limit]  # (code, name, market, cap, sector) — 시총 내림차순
        return pd.DataFrame(
            {"name": [n for _, n, _, _, _ in items],
             "sector": [(s or m) for _, _, m, _, s in items],   # GICS 섹터(없으면 시장)
             "market_cap": [float(cap) for _, _, _, cap, _ in items]},
            index=[c for c, _, _, _, _ in items],
        )

    def _prices_yf(self, tickers: list[str], days: int, progress: ProgressCB) -> pd.DataFrame:
        import yfinance as yf
        ymap = {self._yahoo(c): c for c in tickers}
        start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
        try:
            data = yf.download(list(ymap), start=start, auto_adjust=True,
                               progress=False, threads=True)
        except Exception:
            return pd.DataFrame()
        close = self._extract_close(data, list(ymap))
        if progress:
            progress(1.0, "일봉")
        if close is None:
            return pd.DataFrame()
        close = close.rename(columns=ymap)        # 야후티커 → 종목코드
        return close.sort_index()

    def _quotes_yf(self, tickers: list[str]) -> pd.DataFrame:
        import yfinance as yf
        out = pd.DataFrame(index=tickers, columns=["price", "change_pct"], dtype=float)
        ymap = {self._yahoo(c): c for c in tickers}
        ylist = list(ymap)
        prev = day_price = fresh = None
        try:
            daily = self._extract_close(
                yf.download(ylist, period="5d", interval="1d",
                            progress=False, threads=True, auto_adjust=False), ylist)
            if daily is not None and not daily.dropna(how="all").empty:
                daily = daily.ffill()
                day_price, prev = daily.iloc[-1], (daily.iloc[-2] if len(daily) >= 2 else daily.iloc[-1])
        except Exception:
            pass
        try:
            intr = self._extract_close(
                yf.download(ylist, period="1d", interval="1m",
                            progress=False, threads=True, auto_adjust=False), ylist)
            if intr is not None and not intr.dropna(how="all").empty:
                fresh = intr.ffill().iloc[-1]
        except Exception:
            pass
        if day_price is None and fresh is None:
            return out
        price = fresh.combine_first(day_price) if (fresh is not None and day_price is not None) \
            else (fresh if fresh is not None else day_price)
        price = price.rename(ymap)
        out["price"] = price.reindex(tickers)
        if prev is not None:
            prev = prev.rename(ymap)
            out["change_pct"] = ((price / prev - 1.0) * 100.0).reindex(tickers)
        return out

    def _yf_fundamentals(self, codes: list[str]) -> dict[str, dict]:
        """야후 info에서 펀더멘털 보강(주로 ROE). PER/PBR은 한국 종목엔 대개 없음."""
        self._ensure_info(codes)
        result = {}
        for c in codes:
            info = self._info_cache.get(c, {})
            roe = info.get("returnOnEquity")
            dy = info.get("trailingAnnualDividendYield")
            result[c] = {
                "per": info.get("trailingPE"),
                "pbr": info.get("priceToBook"),
                "dividend_yield": dy * 100.0 if isinstance(dy, (int, float)) else np.nan,
                "roe": roe * 100.0 if isinstance(roe, (int, float)) else np.nan,
                "debt_to_equity": np.nan, "profit_margin": np.nan,
            }
        return result

    # ════════ 공개 인터페이스 (경로 디스패치) ════════
    def get_universe(self, limit: int) -> pd.DataFrame:
        if self._local:
            try:
                return self._universe_fdr(limit)
            except Exception:
                pass
        return self._universe_yf(limit)

    def get_price_history(self, tickers: list[str], days: int,
                          progress: ProgressCB = None) -> pd.DataFrame:
        if self._local:
            df = self._prices_fdr(tickers, days, progress)
            if not df.empty:
                return df
        return self._prices_yf(tickers, days, progress)

    def get_quotes(self, tickers: list[str]) -> pd.DataFrame:
        if self._local:
            try:
                q = self._quotes_fdr(tickers)
                if q["price"].notna().any():
                    return q
            except Exception:
                pass
        return self._quotes_yf(tickers)

    def get_fundamentals(self, tickers: list[str], progress: ProgressCB = None) -> pd.DataFrame:
        # 1) 네이버 먼저(되면 PER/PBR/배당/ROE 완벽). 해외에서 막히면 빈 dict.
        self._ensure_naver(tickers, progress)
        cache = dict(self._fund_cache)
        # 2) 네이버가 아무 것도 못 준 종목만 야후로 보강
        keys = ("per", "pbr", "dividend_yield", "roe")
        missing = [t for t in tickers
                   if all(pd.isna(cache.get(t, {}).get(k, np.nan)) for k in keys)]
        if missing:
            for c, vals in self._yf_fundamentals(missing).items():
                cache[c] = vals
        rows = [cache.get(t, {}) for t in tickers]
        return pd.DataFrame(rows, index=tickers,
                            columns=["per", "pbr", "dividend_yield", "roe",
                                     "debt_to_equity", "profit_margin"])
