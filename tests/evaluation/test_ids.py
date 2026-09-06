from tests.evaluation.conftest import make_candidate
from unbake.evaluation.ids import (
    assign_blind_ids,
    assign_candidate_ids,
    assign_description_fact_ids,
)
from unbake.models import BlindExtraction, DescriptionFacts, Fact, VideoAction


def test_계층_ID_부여():
    c = make_candidate(
        [("절이기", (0, 12_000), ["채 썬다", "버무린다", "절인다"]), ("볶기", (12_000, 30_000), ["볶는다"])],
        ingredients=[("애호박", "1개"), ("소금", None)],
    )
    out = assign_candidate_ids(c)
    assert [s.step_id for s in out.steps] == ["s1", "s2"]
    assert [b.sub_step_id for b in out.steps[0].sub_steps] == ["s1a", "s1b", "s1c"]
    assert out.steps[1].sub_steps[0].sub_step_id == "s2a"
    assert [i.ingredient_id for i in out.ingredients] == ["i1", "i2"]
    # 원본은 불변
    assert c.steps[0].step_id is None


def test_세부단계_26개_초과시_base26():
    c = make_candidate([("긴 단계", None, [f"문장{i}" for i in range(28)])])
    out = assign_candidate_ids(c)
    subs = out.steps[0].sub_steps
    assert subs[0].sub_step_id == "s1a"
    assert subs[25].sub_step_id == "s1z"
    assert subs[26].sub_step_id == "s1aa"
    assert subs[27].sub_step_id == "s1ab"


def test_기존_ID는_결정적으로_덮어쓴다():
    c = make_candidate([("단계", None, ["문장"])])
    c.steps[0].step_id = "LLM이-넣은-값"  # LLM이 ID를 넣어도 무시된다
    out = assign_candidate_ids(c)
    assert out.steps[0].step_id == "s1"


def test_fact_action_ID_부여():
    desc = assign_description_fact_ids(DescriptionFacts(facts=[Fact(text="두부 1모")]))
    assert desc.facts[0].fact_id == "d1"
    blind = assign_blind_ids(
        BlindExtraction(
            audio_facts=[Fact(text="소금 언급")],
            visual_facts=[Fact(text="자막"), Fact(text="자막2")],
            actions=[VideoAction(description="썬다", start_ms=0, end_ms=1000)],
        )
    )
    assert blind.audio_facts[0].fact_id == "au1"
    assert [f.fact_id for f in blind.visual_facts] == ["v1", "v2"]
    assert blind.actions[0].action_id == "a1"
