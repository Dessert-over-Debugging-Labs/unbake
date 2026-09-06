"""ID 부여 — LLM이 아니라 코드가 부여한다.

계층형: 대단계 s1, s2, … / 세부 단계 s1a, s1b, … (26개 초과 시 s1aa 방식)
재료 i1 / claim c1 / 설명란 fact d1 / 음성 fact au1 / 화면 fact v1 / action a1.
위치 기반으로 결정적이며, 기존 값이 있어도 항상 덮어쓴다.
"""

from unbake.models import BlindExtraction, DescriptionFacts, RecipeCandidate


def _alpha(index: int) -> str:
    """0 → a, 25 → z, 26 → aa …"""
    out = ""
    index += 1
    while index > 0:
        index, rem = divmod(index - 1, 26)
        out = chr(ord("a") + rem) + out
    return out


def assign_candidate_ids(candidate: RecipeCandidate) -> RecipeCandidate:
    """대단계·세부 단계·재료에 계층 ID를 부여한 사본을 반환한다."""
    updated = candidate.model_copy(deep=True)
    for si, step in enumerate(updated.steps, start=1):
        step.step_id = f"s{si}"
        for bi, sub in enumerate(step.sub_steps):
            sub.sub_step_id = f"s{si}{_alpha(bi)}"
    for ii, ing in enumerate(updated.ingredients, start=1):
        ing.ingredient_id = f"i{ii}"
    return updated


def assign_description_fact_ids(facts: DescriptionFacts) -> DescriptionFacts:
    updated = facts.model_copy(deep=True)
    for fi, fact in enumerate(updated.facts, start=1):
        fact.fact_id = f"d{fi}"
    return updated


def assign_blind_ids(blind: BlindExtraction) -> BlindExtraction:
    updated = blind.model_copy(deep=True)
    for fi, fact in enumerate(updated.audio_facts, start=1):
        fact.fact_id = f"au{fi}"
    for fi, fact in enumerate(updated.visual_facts, start=1):
        fact.fact_id = f"v{fi}"
    for ai, action in enumerate(updated.actions, start=1):
        action.action_id = f"a{ai}"
    return updated
