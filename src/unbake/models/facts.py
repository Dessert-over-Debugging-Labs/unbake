"""Source facts — Gemini B(블라인드)와 Description Extractor의 출력 계약.

Gemini B는 A 결과·설명란을 보지 못한다(blind 격벽). 이 계약에는 그래서
candidate를 참조하는 필드가 아예 없다 — 격벽은 프롬프트가 아니라 구조가 보장한다.
"""

from unbake.models.base import ApiModel


class Fact(ApiModel):
    """source가 관찰한 사실 하나 (재료·분량 등)."""

    fact_id: str | None = None  # 코드가 부여 (d1 / au1 / v1)
    kind: str = "OTHER"  # INGREDIENT | AMOUNT | TIP | OTHER
    text: str  # 관찰된 원문 표현
    name: str | None = None  # 재료명 (INGREDIENT/AMOUNT일 때)
    amount: str | None = None  # 분량 표현 (있을 때)
    start_ms: int | None = None  # audio/visual만 — 설명란 fact에는 없음
    end_ms: int | None = None


class VideoAction(ApiModel):
    """Gemini B가 추출한 조리 동작 — 세부 단계 매칭의 상대편."""

    action_id: str | None = None  # 코드가 부여 (a1)
    description: str
    start_ms: int
    end_ms: int


class DescriptionFacts(ApiModel):
    """Description Extractor 출력 — 설명란만 읽는다."""

    facts: list[Fact] = []


class BlindExtraction(ApiModel):
    """Gemini B 출력 — 영상만 입력받는다."""

    audio_facts: list[Fact] = []
    visual_facts: list[Fact] = []
    actions: list[VideoAction] = []


class SourceFacts(ApiModel):
    """판정 호출 1회에 들어가는 source 묶음 — 판정 LLM은 이것만 본다(source 격벽)."""

    source: str  # Source enum 값 (DESCRIPTION | AUDIO | VISUAL)
    facts: list[Fact] = []
