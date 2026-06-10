"""quant — 퀀트 라이브 스크리너 코어 패키지.

레이어 구성:
    datasource/  : 시장별 데이터 어댑터(한국·미국)를 공통 인터페이스로 추상화
    factors      : 횡단면 팩터 계산(z-score, 윈저라이즈, 모멘텀/변동성 등)
    behavioral   : 각 팩터의 행동재무학적 근거 + 종목별 행동편향 플래그
    strategies   : 프리셋 전략(가중치 묶음) 및 커스텀 빌더 자료구조
    screener     : 팩터 패널 → 종합점수·랭킹·필터 적용
"""
__all__ = ["factors", "behavioral", "strategies", "screener", "datasource"]
