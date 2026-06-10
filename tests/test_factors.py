"""오프라인 단위 테스트 — 네트워크 없이 팩터 수학을 검증한다.

실행:  python tests/test_factors.py     (pytest 불필요)
또는:  pytest tests/
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

# Windows 콘솔(cp949)에서도 한글/기호가 깨지지 않도록 utf-8로 강제
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 프로젝트 루트를 import 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant import factors, screener, behavioral
from quant.strategies import FactorWeights


def _synthetic_prices(n_days=320, seed=7) -> pd.DataFrame:
    """5개 티커의 합성 일봉. 각기 다른 드리프트/변동성을 부여한다."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n_days)
    specs = {
        "UPTREND":  (0.0030, 0.008),   # 강한 상승 추세
        "DOWNTREND": (-0.0030, 0.008),  # 하락 추세
        "LOWVOL":   (0.0003, 0.004),   # 저변동성
        "HIGHVOL":  (0.0003, 0.035),   # 고변동성
        "FLAT":     (0.0000, 0.008),
    }
    data = {}
    for t, (mu, sigma) in specs.items():
        rets = rng.normal(mu, sigma, n_days)
        data[t] = 100 * np.exp(np.cumsum(rets))
    return pd.DataFrame(data, index=dates)


def test_zscore_properties():
    s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
    z = factors.zscore(s, winsor=False)
    assert abs(z.mean()) < 1e-9
    assert abs(z.std(ddof=0) - 1.0) < 1e-9
    # 상수 입력 → 표준편차 0 → 전부 중립(0)
    z0 = factors.zscore(pd.Series([5.0] * 8))
    assert (z0 == 0).all()


def test_winsorize_clips_outliers():
    s = pd.Series(list(range(100)) + [10_000], dtype=float)
    w = factors.winsorize(s, 0.02, 0.98)
    assert w.max() < 10_000  # 극단값이 잘렸다
    assert w.min() >= s.quantile(0.02) - 1e-9


def test_safe_reciprocal_handles_nonpositive():
    s = pd.Series([2.0, 4.0, 0.0, -5.0, np.nan])
    r = factors._safe_reciprocal(s)
    assert r.iloc[0] == 0.5 and r.iloc[1] == 0.25
    assert pd.isna(r.iloc[2]) and pd.isna(r.iloc[3]) and pd.isna(r.iloc[4])


def test_momentum_directionality():
    px = _synthetic_prices()
    mom = factors.momentum_12_1(px)
    assert mom["UPTREND"] > mom["FLAT"] > mom["DOWNTREND"]


def test_volatility_directionality():
    px = _synthetic_prices()
    vol = factors.annualized_volatility(px)
    assert vol["HIGHVOL"] > vol["LOWVOL"]
    # 저변동성일수록 z_lowvol(부호반전 z) 점수가 높아야 한다
    z = factors.zscore(-vol)
    assert z["LOWVOL"] > z["HIGHVOL"]


def test_build_panel_and_scores():
    px = _synthetic_prices()
    tickers = list(px.columns)
    universe = pd.DataFrame(
        {"name": tickers, "sector": ["테크", "에너지", "필수소비", "바이오", "산업재"],
         "market_cap": [9e11, 5e11, 3e11, 1e11, 2e11]},
        index=tickers,
    )
    fundamentals = pd.DataFrame(
        {"per": [8, 25, 12, np.nan, 15],
         "pbr": [1.0, 3.0, 1.2, 0.5, 2.0],
         "dividend_yield": [3.0, 0.0, 4.0, 0.0, 1.5],
         "roe": [18, 10, 14, -5, 9],
         "debt_to_equity": [40, 120, 30, 200, 80],
         "profit_margin": [20, 8, 15, -10, 11]},
        index=tickers,
    )
    panel = factors.build_factor_panel(px, fundamentals, universe)
    # 팩터 컬럼이 모두 존재하고 결측 없음(중립 0으로 채움)
    for col in factors.FACTOR_COLUMNS:
        assert col in panel.columns
        assert panel[col].notna().all()

    scored = screener.compute_scores(panel, FactorWeights(0.25, 0.25, 0.25, 0.25))
    assert scored["rank"].tolist() == sorted(scored["rank"].tolist())  # 1..N 순서
    assert scored["composite"].is_monotonic_decreasing                  # 내림차순 정렬
    assert "flags" in scored.columns


def test_max_per_filter():
    px = _synthetic_prices()
    tickers = list(px.columns)
    universe = pd.DataFrame(
        {"name": tickers, "sector": [""] * 5, "market_cap": [1e12] * 5}, index=tickers)
    fundamentals = pd.DataFrame(
        {"per": [50, 4, 10, 30, 8], "pbr": [5, 0.4, 1, 3, 1.1],
         "dividend_yield": [0, 0, 5, 1, 2], "roe": [5, 3, 12, 8, 10],
         "debt_to_equity": [np.nan] * 5, "profit_margin": [np.nan] * 5},
        index=tickers)
    panel = factors.build_factor_panel(px, fundamentals, universe)
    scored = screener.compute_scores(panel, FactorWeights(0.25, 0.25, 0.25, 0.25))

    # 최대 PER 20 → PER 50/30 종목은 (양수이므로) 탈락
    f = screener.apply_filters(scored, max_per=20)
    kept_per = pd.to_numeric(f["per"], errors="coerce")
    assert ((kept_per <= 20) | ~(kept_per > 0)).all()


def test_behavioral_flags_trigger():
    """임계치를 직접 겨냥해 각 행동편향 플래그가 정확히 발화하는지 검증."""
    panel = pd.DataFrame(
        {"name": ["HOT", "LOTTO", "TRAP", "NORMAL"],
         "mom_12_1": [0.85, 0.10, -0.50, 0.05],     # HOT: 과열(>0.60)
         "vol_6m": [0.40, 0.70, 0.30, 0.20],        # LOTTO: 복권형(>0.55)
         "drawdown_6m": [-0.05, -0.10, -0.45, -0.08],  # TRAP: 깊은 낙폭(<-0.35)
         "per": [30, 25, 4.0, 15], "pbr": [3, 3, 0.5, 1.5]},
        index=["HOT", "LOTTO", "TRAP", "NORMAL"])
    flags = behavioral.behavioral_flags(panel)
    assert "과열" in flags.loc["HOT", "flags"]
    assert "복권형" in flags.loc["LOTTO", "flags"]
    assert "가치함정" in flags.loc["TRAP", "flags"]      # 저PER(4) + 깊은 낙폭
    assert flags.loc["NORMAL", "flags"] == ""


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK]   {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {t.__name__}  --  {e!r}")
        except Exception as e:  # noqa
            failed += 1
            print(f"  [FAIL] {t.__name__}  --  ERROR {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} 통과")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
