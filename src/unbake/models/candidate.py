"""RecipeCandidate — Gemini A가 출력하는 얇은 중간 표현(IR).

백엔드 DTO(RecipeCreateRequest)가 아니다. 평가·사람 수정(revision)의 대상이며,
결정적 normalization/mapping을 거쳐야 백엔드 계약이 된다 (docs/architecture.md).

계층 구조는 실서비스 형식 그대로: 대단계(step)에만 timestamp가 있고,
세부 단계(subStep)는 문장 하나가 동작 하나를 담는다.
"""

from unbake.models.base import ApiModel


class SubStep(ApiModel):
    """세부 단계 — 의미 매칭의 단위."""

    sub_step_id: str | None = None  # 코드가 부여 (s1a) — LLM은 넣지 않는다
    text: str


class CandidateStep(ApiModel):
    """대단계 — temporal 평가의 단위. timestamp는 여기에만 존재한다."""

    step_id: str | None = None  # 코드가 부여 (s1)
    title: str
    start_ms: int | None = None
    end_ms: int | None = None
    sub_steps: list[SubStep] = []


class CandidateIngredient(ApiModel):
    ingredient_id: str | None = None  # 코드가 부여 (i1)
    group: str = "MAIN"  # MAIN | SEASONING
    name: str
    amount: str | None = None  # 미확인이면 None — 추측 분량 생성 금지


class RecipeCandidate(ApiModel):
    candidate_id: str | None = None
    video_id: str
    duration_ms: int | None = None
    dish_name: str
    title: str | None = None
    summary: str | None = None
    servings: str | None = None
    cook_time_min: int | None = None
    difficulty: str | None = None  # EASY | NORMAL | HARD
    ingredients: list[CandidateIngredient] = []
    steps: list[CandidateStep] = []
    tags: list[dict] = []

    def iter_sub_steps(self):
        """(step, sub_step) 순회 — 전역 순서는 대단계 순서 → 세부 단계 순서."""
        for step in self.steps:
            for sub in step.sub_steps:
                yield step, sub
