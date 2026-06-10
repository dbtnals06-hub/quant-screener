"""행동재무 레이어 — '왜 이 팩터가 돈이 되는가'를 편향으로 설명하고,
개별 종목의 위험 신호를 행동편향 관점에서 플래그한다.

효율적 시장 가설이 옳다면 아래 팩터들의 초과수익은 0이어야 한다.
그럼에도 수십 년간 지속된다는 사실 자체가, 시장가격이 '합리적 기대'가 아니라
'편향된 다수의 심리'로 형성된다는 행동경제학의 핵심 주장을 뒷받침한다.
"""
from __future__ import annotations

import pandas as pd


# 팩터 → (대표 편향, 메커니즘 해설, 핵심 레퍼런스)
FACTOR_BEHAVIOR: dict[str, dict[str, str]] = {
    "value": {
        "factor_kr": "가치",
        "bias": "과잉반응 · 외삽 편향(Extrapolation)",
        "mechanism": (
            "투자자는 최근의 나쁜 실적을 먼 미래까지 직선으로 연장해 헐값에 던지고, "
            "잘나가는 기업의 성장은 영원할 것처럼 과대평가한다. 그 결과 '싼 주식'은 "
            "기대를 너무 낮게, '비싼 주식'은 너무 높게 반영한다 — 평균회귀가 차익을 만든다."
        ),
        "ref": "De Bondt & Thaler (1985), Lakonishok–Shleifer–Vishny (1994)",
    },
    "momentum": {
        "factor_kr": "모멘텀",
        "bias": "과소반응 · 군집행동(Herding) · 처분효과",
        "mechanism": (
            "새 정보가 가격에 천천히 스며든다(과소반응). 동시에 투자자는 오른 주식을 "
            "너무 일찍 팔고(처분효과) 군중을 뒤늦게 따라붙어, 추세가 한동안 지속된다."
        ),
        "ref": "Jegadeesh & Titman (1993), Hong & Stein (1999)",
    },
    "quality": {
        "factor_kr": "퀄리티",
        "bias": "제한된 주의(Limited Attention)",
        "mechanism": (
            "시장은 자극적인 스토리·뉴스에 주의를 쏟느라 높은 ROE·낮은 부채 같은 "
            "지루한 우량 지표를 과소평가한다. 꾸준한 현금흐름이 결국 보상받는다."
        ),
        "ref": "Sloan (1996), Novy-Marx (2013)",
    },
    "lowvol": {
        "factor_kr": "저변동성",
        "bias": "복권선호 · 과신(Overconfidence)",
        "mechanism": (
            "사람들은 '한 방'을 노려 변동성 큰 복권형 주식에 과도한 프리미엄을 지불한다. "
            "반대로 지루한 저변동성 주식은 외면받아 위험 대비 수익이 오히려 높아진다 — "
            "고위험=고수익이라는 교과서 직관을 뒤집는 '저변동성 이상현상'."
        ),
        "ref": "Baker–Bradley–Wurgler (2011), Frazzini & Pedersen (2014)",
    },
}


# 종목별 행동편향 플래그 임계치
_RUNUP_HOT = 0.60          # 12-1 모멘텀이 +60% 초과 → 과열/처분효과 군집 신호
_VOL_LOTTERY = 0.55        # 연율 변동성 55% 초과 → 복권형
_DEEP_DRAWDOWN = -0.35     # 6개월 낙폭 -35% 미만 → 추락 중
_CHEAP_PER = 5.0           # PER 5 미만(양수) → 매우 쌈


def behavioral_flags(panel: pd.DataFrame) -> pd.DataFrame:
    """패널 각 종목에 대해 행동편향 위험 플래그(이모지 태그)와 코멘트를 생성.

    반환: index=티커, columns=['flags', 'flag_detail']
    """
    flags, details = [], []
    for tkr, row in panel.iterrows():
        tags, notes = [], []
        mom = row.get("mom_12_1")
        vol = row.get("vol_6m")
        dd = row.get("drawdown_6m")
        per = row.get("pbr") if False else row.get("per")  # 가독성용

        # 과열 — 처분효과/군집에 의한 모멘텀, 단 되돌림(모멘텀 크래시) 위험
        if pd.notna(mom) and mom > _RUNUP_HOT:
            tags.append("🔥과열")
            notes.append("최근 12개월 급등 — 군집·처분효과 신호. 모멘텀 크래시(급반락) 주의.")

        # 복권형 — 복권선호 프리미엄이 끼어 기대수익이 낮을 수 있음
        if pd.notna(vol) and vol > _VOL_LOTTERY:
            tags.append("🎰복권형")
            notes.append("변동성 과대 — 복권선호 프리미엄 탑재 가능성, 위험 대비 수익 불리.")

        # 가치함정 — 싸지만 추세가 무너진 종목(역발상의 함정)
        if pd.notna(per) and 0 < per < _CHEAP_PER and pd.notna(dd) and dd < _DEEP_DRAWDOWN:
            tags.append("⚠️가치함정")
            notes.append("저PER이지만 깊은 하락 추세 — '싼 데는 이유가 있다' 가치함정 의심.")

        flags.append(" ".join(tags))
        details.append(" / ".join(notes))

    return pd.DataFrame({"flags": flags, "flag_detail": details}, index=panel.index)


def top_pick_commentary(row: pd.Series, weights) -> str:
    """1위 종목에 대한 '행동경제학 교수' 톤의 한 문단 해설을 생성."""
    contribs = {
        "가치": weights.value * row.get("z_value", 0.0),
        "모멘텀": weights.momentum * row.get("z_momentum", 0.0),
        "퀄리티": weights.quality * row.get("z_quality", 0.0),
        "저변동성": weights.lowvol * row.get("z_lowvol", 0.0),
    }
    driver = max(contribs, key=contribs.get)
    key = {"가치": "value", "모멘텀": "momentum", "퀄리티": "quality", "저변동성": "lowvol"}[driver]
    info = FACTOR_BEHAVIOR[key]
    name = row.get("name") or row.name
    return (
        f"**{name}** 의 상위 랭크를 견인한 핵심 동력은 **{driver}** 팩터입니다. "
        f"이 알파의 행동경제학적 뿌리는 *{info['bias']}* 입니다 — {info['mechanism']} "
        f"({info['ref']})"
    )
