"""평가 코어 테스트 공용 빌더 — synthetic fixture는 여기서 조립한다."""

import pytest

from unbake.evaluation.recovery import PortResponse
from unbake.models import (
    BlindExtraction,
    CandidateIngredient,
    CandidateStep,
    ClaimSourceJudgement,
    DescriptionFacts,
    Fact,
    RecipeCandidate,
    SubStep,
    SubStepMapping,
    SubStepMappingStatus,
    VideoAction,
)


def make_candidate(
    steps: list[tuple[str, tuple[int, int] | None, list[str]]],
    ingredients: list[tuple[str, str | None]] | None = None,
    duration_ms: int | None = 600_000,
) -> RecipeCandidate:
    """steps: (제목, (startMs, endMs) 또는 None, 세부 단계 문장들)"""
    return RecipeCandidate(
        video_id="vid-test",
        dish_name="테스트찌개",
        duration_ms=duration_ms,
        ingredients=[
            CandidateIngredient(name=name, amount=amount)
            for name, amount in (ingredients or [])
        ],
        steps=[
            CandidateStep(
                title=title,
                start_ms=span[0] if span else None,
                end_ms=span[1] if span else None,
                sub_steps=[SubStep(text=t) for t in texts],
            )
            for title, span, texts in steps
        ],
    )


def make_actions(spans: list[tuple[int, int]]) -> list[VideoAction]:
    return [
        VideoAction(action_id=f"a{i}", description=f"동작 {i}", start_ms=s, end_ms=e)
        for i, (s, e) in enumerate(spans, start=1)
    ]


class FakeJudge:
    """source별 verdict 표를 그대로 돌려주는 판정기.

    verdicts: {source값: {claimId: (verdict, observed_value)}} — 없는 claim은 UNKNOWN.
    """

    def __init__(self, verdicts: dict[str, dict[str, tuple[str, str | None]]] | None = None):
        self.verdicts = verdicts or {}
        self.calls: list[tuple[str, list[str] | None]] = []

    def judge(self, claims, facts, requested_claim_ids):
        self.calls.append((facts.source, requested_claim_ids))
        table = self.verdicts.get(facts.source, {})
        wanted = requested_claim_ids or [c.claim_id for c in claims]
        items = []
        for cid in wanted:
            verdict, observed = table.get(cid, ("UNKNOWN", None))
            items.append(
                ClaimSourceJudgement(claim_id=cid, verdict=verdict, observed_value=observed)
            )
        return PortResponse(items=items, model="fake-judge", prompt_version="t1", prompt_hash="h")


class FakeMatcher:
    """미리 정한 매핑 제안을 돌려주는 매처.

    mapping: {subStepId: (status, [actionId...])} — 없는 세부 단계는 UNMATCHED.
    """

    def __init__(self, mapping: dict[str, tuple[str, list[str]]]):
        self.mapping = mapping

    def match(self, candidate, actions, requested_sub_step_ids):
        wanted = requested_sub_step_ids or [
            sub.sub_step_id for _s, sub in candidate.iter_sub_steps()
        ]
        items = []
        for sid in wanted:
            status, action_ids = self.mapping.get(sid, (SubStepMappingStatus.UNMATCHED, []))
            items.append(SubStepMapping(sub_step_id=sid, status=status, action_ids=action_ids))
        return PortResponse(items=items, model="fake-matcher", prompt_version="t1", prompt_hash="h")


@pytest.fixture
def empty_facts() -> DescriptionFacts:
    return DescriptionFacts(facts=[])


@pytest.fixture
def empty_blind() -> BlindExtraction:
    return BlindExtraction()


def ingredient_fact(fact_id: str | None, name: str, text: str | None = None) -> Fact:
    return Fact(fact_id=fact_id, kind="INGREDIENT", name=name, text=text or name)
