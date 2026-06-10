"""전역 설정값.

한 곳에서 기본 파라미터를 관리한다. UI(사이드바)에서 대부분 덮어쓸 수 있다.
일부 값은 환경변수로도 덮어쓸 수 있다(예: 빠른 기동을 위해 QS_UNIVERSE_SIZE=30).
"""
from __future__ import annotations

import os


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


# ── 데이터 적재 ─────────────────────────────────────────────
DEFAULT_UNIVERSE_SIZE = _env_int("QS_UNIVERSE_SIZE", 60)  # 시총 상위 N 종목으로 유니버스 구성
PRICE_HISTORY_DAYS = 420         # 약 1.5년 — 12-1 모멘텀(252일)+버퍼
BASE_CACHE_TTL = 6 * 60 * 60     # 무거운 일봉/펀더멘털 캐시 수명(초) = 6시간

# ── 실시간 폴링 ─────────────────────────────────────────────
DEFAULT_POLL_SECONDS = 30
MIN_POLL_SECONDS = 5
MAX_POLL_SECONDS = 120

# ── 팩터 계산 ───────────────────────────────────────────────
MOMENTUM_LOOKBACK = 252          # 12개월(거래일)
MOMENTUM_SKIP = 21               # 최근 1개월 제외(단기 반전 회피) → "12-1 모멘텀"
VOL_WINDOW = 126                 # 저변동성 팩터용 6개월 변동성
WINSOR_LOWER = 0.02              # 이상치 윈저라이즈 하한 분위
WINSOR_UPPER = 0.98              # 상한 분위

# ── 시장 코드 ───────────────────────────────────────────────
MARKET_KR = "KR"
MARKET_US = "US"

LABEL_KR = "한국 (KOSPI/KOSDAQ)"
LABEL_US = "미국 (NYSE/NASDAQ)"

MARKET_LABELS = {
    LABEL_KR: MARKET_KR,
    LABEL_US: MARKET_US,
}


def _default_market_label() -> str:
    """기본 시장 선택값.

    한국(KRX/네이버)은 해외 IP에서 차단되므로, 비-Windows 환경(주로 Linux 클라우드
    서버=Streamlit Cloud)에서는 미국을 기본값으로 둔다. 로컬 Windows에서는 한국 유지.
    환경변수 QS_DEFAULT_MARKET=US|KR 로 강제 지정 가능.
    """
    env = os.environ.get("QS_DEFAULT_MARKET", "").upper()
    if env == "US":
        return LABEL_US
    if env == "KR":
        return LABEL_KR
    import platform
    return LABEL_US if platform.system() != "Windows" else LABEL_KR


DEFAULT_MARKET_LABEL = _default_market_label()
