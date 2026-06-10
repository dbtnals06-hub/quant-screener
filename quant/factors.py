"""횡단면(cross-sectional) 팩터 엔진.

원칙
----
1. 모든 팩터는 '클수록 좋다(높은 기대수익)'는 방향으로 부호를 통일한다.
2. 원시값은 윈저라이즈 후 z-score로 표준화하여 서로 다른 단위를 합산 가능하게 만든다.
3. 결측은 0(중립)으로 처리하되, 원시값 컬럼은 NaN을 보존해 화면에 그대로 보여준다.

여기서 만드는 4대 학술 팩터(가치·모멘텀·퀄리티·저변동성)는 모두
'시장이 완전 효율적이라면 존재하지 말아야 할' 이상현상이며, 각각 뚜렷한
행동편향에 뿌리를 둔다(자세한 해설은 behavioral.py).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


# ── 표준화 유틸 ─────────────────────────────────────────────
def winsorize(s: pd.Series, lower: float = config.WINSOR_LOWER,
              upper: float = config.WINSOR_UPPER) -> pd.Series:
    """분위 기반 윈저라이즈. 소수 극단값이 z-score를 지배하는 것을 막는다."""
    s = pd.to_numeric(s, errors="coerce")
    valid = s.dropna()
    if valid.empty:
        return s
    lo, hi = valid.quantile(lower), valid.quantile(upper)
    return s.clip(lower=lo, upper=hi)


def zscore(s: pd.Series, winsor: bool = True) -> pd.Series:
    """횡단면 z-score. 표준편차가 0이거나 유효표본이 1개 이하면 0(중립) 반환."""
    s = pd.to_numeric(s, errors="coerce")
    if winsor:
        s = winsorize(s)
    mu = s.mean(skipna=True)
    sd = s.std(skipna=True, ddof=0)
    if not np.isfinite(sd) or sd == 0:
        return pd.Series(0.0, index=s.index)
    return (s - mu) / sd


def _safe_reciprocal(s: pd.Series) -> pd.Series:
    """1/x. 단, x<=0(적자 PER, 자본잠식 PBR 등)은 의미가 없으므로 NaN 처리."""
    s = pd.to_numeric(s, errors="coerce")
    out = s.where(s > 0)
    return 1.0 / out


# ── 가격 기반 팩터 (일봉 wide DataFrame: index=날짜, columns=티커) ──
def total_return(prices: pd.DataFrame, lookback: int, skip: int = 0) -> pd.Series:
    """[t-lookback, t-skip] 구간 누적수익률. 데이터가 짧으면 가능한 만큼으로 보정."""
    px = prices.ffill()
    n = len(px)
    if n < 2:
        return pd.Series(np.nan, index=px.columns)
    skip = min(skip, n - 2)
    lookback = min(lookback, n - 1)
    if lookback <= skip:
        lookback = skip + 1
    end = px.iloc[-1 - skip]
    start = px.iloc[-1 - lookback]
    ret = end / start.replace(0, np.nan) - 1.0
    return ret


def momentum_12_1(prices: pd.DataFrame) -> pd.Series:
    """12-1 모멘텀: 최근 1개월을 제외한 12개월 수익률(단기 반전 노이즈 제거)."""
    return total_return(prices, lookback=config.MOMENTUM_LOOKBACK,
                        skip=config.MOMENTUM_SKIP)


def annualized_volatility(prices: pd.DataFrame, window: int = config.VOL_WINDOW) -> pd.Series:
    """최근 `window` 거래일 일간수익률의 연율화 변동성."""
    rets = prices.ffill().pct_change()
    tail = rets.iloc[-window:]
    if tail.empty:
        return pd.Series(np.nan, index=prices.columns)
    return tail.std(ddof=0) * np.sqrt(252)


def trailing_drawdown(prices: pd.DataFrame, window: int = config.VOL_WINDOW) -> pd.Series:
    """최근 구간 고점 대비 현재 낙폭(MDD 근사). 행동 플래그(가치함정 등)에 사용."""
    px = prices.ffill().iloc[-window:]
    if px.empty:
        return pd.Series(np.nan, index=prices.columns)
    peak = px.cummax().iloc[-1]
    last = px.iloc[-1]
    return last / peak - 1.0


# ── 팩터 패널 조립 ─────────────────────────────────────────
RAW_COLUMNS = [
    "name", "sector", "market_cap",
    "per", "pbr", "dividend_yield", "roe", "debt_to_equity", "profit_margin",
    "mom_12_1", "vol_6m", "drawdown_6m",
]
FACTOR_COLUMNS = ["z_value", "z_momentum", "z_quality", "z_lowvol"]


def build_factor_panel(prices: pd.DataFrame,
                       fundamentals: pd.DataFrame,
                       universe: pd.DataFrame) -> pd.DataFrame:
    """가격·펀더멘털·유니버스 메타를 합쳐 종목×팩터 패널을 만든다.

    반환 DataFrame
        index            : 티커
        RAW_COLUMNS      : 화면 표시용 원시값
        FACTOR_COLUMNS   : 표준화된 4대 팩터 점수(클수록 우수)
    """
    idx = universe.index
    panel = pd.DataFrame(index=idx)

    # 메타/원시값
    panel["name"] = universe.get("name")
    panel["sector"] = universe.get("sector")
    panel["market_cap"] = universe.get("market_cap")

    for col in ["per", "pbr", "dividend_yield", "roe", "debt_to_equity", "profit_margin"]:
        panel[col] = fundamentals[col].reindex(idx) if col in fundamentals else np.nan

    panel["mom_12_1"] = momentum_12_1(prices).reindex(idx)
    panel["vol_6m"] = annualized_volatility(prices).reindex(idx)
    panel["drawdown_6m"] = trailing_drawdown(prices).reindex(idx)

    # ── 가치(Value): 이익수익률(1/PER) + 장부/시가(1/PBR) + 배당수익률
    earnings_yield = _safe_reciprocal(panel["per"])
    book_to_market = _safe_reciprocal(panel["pbr"])
    div = pd.to_numeric(panel["dividend_yield"], errors="coerce")
    panel["z_value"] = pd.concat(
        [zscore(earnings_yield), zscore(book_to_market), zscore(div)], axis=1
    ).mean(axis=1, skipna=True)

    # ── 모멘텀(Momentum): 12-1 수익률 (클수록 좋음)
    panel["z_momentum"] = zscore(panel["mom_12_1"])

    # ── 퀄리티(Quality): 높은 ROE + 낮은 부채비율 + 높은 이익률
    q_parts = [zscore(pd.to_numeric(panel["roe"], errors="coerce"))]
    if panel["debt_to_equity"].notna().any():
        q_parts.append(zscore(-pd.to_numeric(panel["debt_to_equity"], errors="coerce")))
    if panel["profit_margin"].notna().any():
        q_parts.append(zscore(pd.to_numeric(panel["profit_margin"], errors="coerce")))
    panel["z_quality"] = pd.concat(q_parts, axis=1).mean(axis=1, skipna=True)

    # ── 저변동성(Low-Vol): 변동성이 낮을수록 점수가 높도록 부호 반전
    panel["z_lowvol"] = zscore(-panel["vol_6m"])

    # 팩터 결측은 중립(0)
    panel[FACTOR_COLUMNS] = panel[FACTOR_COLUMNS].fillna(0.0)
    return panel
