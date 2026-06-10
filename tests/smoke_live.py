"""라이브 통합 스모크 테스트 — 실제 네트워크로 어댑터 end-to-end 검증.

※ 네트워크가 필요하며 장 마감/휴장 시 일부 값이 결측일 수 있습니다.
실행:  python tests/smoke_live.py [kr|us|both]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import config
from quant.datasource import get_source
from quant.factors import build_factor_panel
from quant.screener import compute_scores
from quant.strategies import PRESETS


def check(market: str, limit: int = 6) -> bool:
    name = "한국" if market == config.MARKET_KR else "미국"
    print(f"\n{'='*60}\n[{name}] 어댑터 라이브 점검 (유니버스 {limit})\n{'='*60}")
    ds = get_source(market)

    uni = ds.get_universe(limit)
    print(f"  유니버스: {len(uni)}종목  예) "
          + ", ".join(f"{t}:{uni.loc[t, 'name']}" for t in uni.index[:3]))
    assert not uni.empty, "유니버스가 비었습니다"
    tickers = list(uni.index)

    prices = ds.get_price_history(tickers, config.PRICE_HISTORY_DAYS)
    print(f"  일봉: shape={prices.shape}, 최근일={prices.index[-1].date() if not prices.empty else 'N/A'}")
    assert not prices.empty, "일봉이 비었습니다"

    fund = ds.get_fundamentals(tickers)
    have_per = int(fund['per'].notna().sum())
    print(f"  펀더멘털: PER 보유 {have_per}/{len(tickers)}, "
          f"배당 보유 {int(fund['dividend_yield'].notna().sum())}, "
          f"ROE 보유 {int(fund['roe'].notna().sum())}")

    quotes = ds.get_quotes(tickers)
    have_px = int(quotes['price'].notna().sum())
    print(f"  실시간시세: 현재가 보유 {have_px}/{len(tickers)}, "
          f"등락률 보유 {int(quotes['change_pct'].notna().sum())}")

    panel = build_factor_panel(prices, fund, uni)
    scored = compute_scores(panel, PRESETS['멀티팩터 (균형)'])
    print(f"  팩터패널: {panel.shape}, 종합점수 NaN={int(scored['composite'].isna().sum())}")
    top = scored.iloc[0]
    print(f"  1위: {top['name']} (점수 {top['composite']:.2f}, "
          f"가치 {top['z_value']:+.2f}/모멘텀 {top['z_momentum']:+.2f}/"
          f"퀄리티 {top['z_quality']:+.2f}/저변동 {top['z_lowvol']:+.2f})")
    assert scored['composite'].notna().any(), "종합점수가 전부 NaN"
    print(f"  [OK] {name} 어댑터 정상")
    return True


if __name__ == "__main__":
    arg = (sys.argv[1] if len(sys.argv) > 1 else "both").lower()
    markets = {"kr": [config.MARKET_KR], "us": [config.MARKET_US],
               "both": [config.MARKET_US, config.MARKET_KR]}[arg]
    ok = 0
    for m in markets:
        try:
            ok += 1 if check(m) else 0
        except Exception as e:
            print(f"  [FAIL] {m}: {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(markets)} 시장 정상")
    sys.exit(0 if ok == len(markets) else 1)
