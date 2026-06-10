"""Streamlit 앱 헤드리스 실행 테스트 (공식 AppTest).

app.py 를 실제로 실행해 UI 코드(Styler·altair·fragment·column_config)에서
예외가 발생하지 않는지, 양 시장(KR/US) 경로가 모두 렌더되는지 검증한다.
※ 네트워크 필요. 속도를 위해 유니버스를 작게 패치한다.

실행:  python tests/test_app.py
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
config.DEFAULT_UNIVERSE_SIZE = 12  # 테스트 속도용 — 슬라이더 기본값을 작게

from streamlit.testing.v1 import AppTest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _check(at, market_label: str) -> None:
    assert len(at.exception) == 0, \
        f"[{market_label}] 앱 예외: {[str(e.value) for e in at.exception]}"
    assert len(at.dataframe) >= 1, f"[{market_label}] 스크리너 테이블이 렌더되지 않음"
    n_rows = at.dataframe[0].value.shape[0]
    print(f"  [OK] {market_label}: 예외 0, 테이블 {n_rows}행, "
          f"메트릭 {len(at.metric)}개, 차트 {len(at.altair_chart) if hasattr(at, 'altair_chart') else 'n/a'}")


def main() -> int:
    print("앱 헤드리스 실행 (유니버스 12, 네트워크 사용)…")

    # 1) 기본(한국) 경로
    at = AppTest.from_file(APP, default_timeout=240)
    at.run()
    _check(at, "한국")

    # 2) 미국으로 전환
    at.selectbox[0].set_value("미국 (NYSE/NASDAQ)").run()
    _check(at, "미국")

    # 3) 커스텀 전략 + 가치함정 제외 토글 등 부가 경로
    at.selectbox[1].set_value("커스텀 (직접 조립)").run()
    assert len(at.exception) == 0, f"커스텀 전략 예외: {[str(e.value) for e in at.exception]}"
    print("  [OK] 커스텀 전략 경로: 예외 0")

    print("\n앱 검증 통과 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
