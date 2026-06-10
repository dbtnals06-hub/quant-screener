"""스크리닝 엔진 — 팩터 패널에 가중치를 적용해 종합점수·랭킹을 만들고,
사용자 필터(시총·PER·섹터)를 적용한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .strategies import FactorWeights
from . import behavioral


def compute_scores(panel: pd.DataFrame, weights: FactorWeights) -> pd.DataFrame:
    """가중 종합점수(composite)와 순위(rank), 백분위(percentile)를 계산해 정렬 반환."""
    w = weights.normalized()
    out = panel.copy()
    out["composite"] = (
        w.value * out["z_value"]
        + w.momentum * out["z_momentum"]
        + w.quality * out["z_quality"]
        + w.lowvol * out["z_lowvol"]
    )
    out = out.sort_values("composite", ascending=False)
    out["rank"] = np.arange(1, len(out) + 1)
    # 0~100 백분위(클수록 우수)
    out["percentile"] = out["composite"].rank(pct=True) * 100.0

    # 행동편향 플래그 부착
    flags = behavioral.behavioral_flags(out)
    out = out.join(flags)
    return out


def apply_filters(panel: pd.DataFrame,
                  min_market_cap: float | None = None,
                  max_per: float | None = None,
                  min_dividend: float | None = None,
                  sectors: list[str] | None = None,
                  exclude_value_traps: bool = False) -> pd.DataFrame:
    """하드 필터. 조건을 만족하지 못하는 종목을 제거한다."""
    mask = pd.Series(True, index=panel.index)

    if min_market_cap:
        mask &= panel["market_cap"].fillna(0) >= min_market_cap
    if max_per:
        per = pd.to_numeric(panel["per"], errors="coerce")
        # 적자(PER NaN/<=0)는 가치 필터에서 제외하지 않고 통과(별도 판단)
        mask &= (per <= max_per) | ~(per > 0)
    if min_dividend:
        mask &= pd.to_numeric(panel["dividend_yield"], errors="coerce").fillna(0) >= min_dividend
    if sectors:
        mask &= panel["sector"].isin(sectors)
    if exclude_value_traps and "flags" in panel:
        mask &= ~panel["flags"].fillna("").str.contains("가치함정")

    return panel[mask]


# 화면 표시용 컬럼 순서 & 한글 헤더
DISPLAY_COLUMNS = {
    "rank": "순위",
    "name": "종목",
    "sector": "섹터",
    "price": "현재가",
    "change_pct": "등락률(%)",
    "composite": "종합점수",
    "percentile": "백분위",
    "z_value": "가치",
    "z_momentum": "모멘텀",
    "z_quality": "퀄리티",
    "z_lowvol": "저변동성",
    "per": "PER",
    "pbr": "PBR",
    "dividend_yield": "배당%",
    "roe": "ROE%",
    "mom_12_1": "12-1수익률",
    "vol_6m": "변동성",
    "market_cap": "시가총액",
    "flags": "행동신호",
}
