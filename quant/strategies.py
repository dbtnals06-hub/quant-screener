"""전략 = 4대 팩터에 부여하는 가중치 묶음.

프리셋은 학계·실무의 정형화된 조합을 제공하고, 커스텀은 사용자가
사이드바 슬라이더로 직접 가중치를 조립한다(app.py).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class FactorWeights:
    """4대 팩터 가중치. 합이 1이 아니어도 normalized()로 정규화해 사용한다."""
    value: float = 0.25
    momentum: float = 0.25
    quality: float = 0.25
    lowvol: float = 0.25

    def normalized(self) -> "FactorWeights":
        total = abs(self.value) + abs(self.momentum) + abs(self.quality) + abs(self.lowvol)
        if total == 0:
            # 전부 0이면 균등 가중으로 폴백
            return FactorWeights(0.25, 0.25, 0.25, 0.25)
        return FactorWeights(
            self.value / total,
            self.momentum / total,
            self.quality / total,
            self.lowvol / total,
        )

    def as_dict(self) -> dict:
        return asdict(self)


# 프리셋: 사용자가 "모두 추가" 요청 → 4가지 대표 전략 제공
PRESETS: dict[str, FactorWeights] = {
    "멀티팩터 (균형)": FactorWeights(0.25, 0.25, 0.25, 0.25),
    "행동재무 (모멘텀·저변동성)": FactorWeights(value=0.20, momentum=0.40, quality=0.10, lowvol=0.30),
    "가치투자 (저PER·저PBR·고배당)": FactorWeights(value=0.70, momentum=0.10, quality=0.20, lowvol=0.00),
    "퀄리티 (우량주)": FactorWeights(value=0.20, momentum=0.10, quality=0.60, lowvol=0.10),
}

CUSTOM_LABEL = "커스텀 (직접 조립)"

# 각 프리셋의 한 줄 설명(행동경제학 관점)
PRESET_NOTES: dict[str, str] = {
    "멀티팩터 (균형)":
        "서로 약상관인 4개 이상현상을 동일가중으로 분산. 단일 편향에 베팅하지 않아 가장 견고한 출발점.",
    "행동재무 (모멘텀·저변동성)":
        "과소반응(모멘텀)과 복권선호 회피(저변동성)에 집중 — 투자자 심리에서 직접 파생되는 두 알파.",
    "가치투자 (저PER·저PBR·고배당)":
        "과잉반응으로 싸진 종목에 베팅하는 역발상. 단순·직관적이나 '가치함정' 위험을 동반.",
    "퀄리티 (우량주)":
        "높은 ROE·낮은 부채의 우량 기업. 시장이 펀더멘털 품질에 무관심(제한된 주의)할 때 보상.",
}
