"""Claim — 후보 레시피에서 추출한 검증 가능한 주장.

재료 존재(EXISTENCE)와 분량(AMOUNT)은 별도 claim이다 —
"재료는 맞고 양은 틀림"을 보존해야 한다 (docs/architecture.md).
"""

from enum import StrEnum

from unbake.models.base import ApiModel


class ClaimAspect(StrEnum):
    EXISTENCE = "EXISTENCE"  # 재료가 실제로 쓰였다
    AMOUNT = "AMOUNT"  # 분량이 이 값이다


class Claim(ApiModel):
    claim_id: str  # 코드가 부여 (c1)
    aspect: ClaimAspect
    subject: str  # 재료명
    value: str | None = None  # AMOUNT일 때 분량 표현
    text: str  # 판정 LLM에 보여줄 문장형 표현
    evidence_refs: list[str] = []  # 근거 ingredientId / subStepId
