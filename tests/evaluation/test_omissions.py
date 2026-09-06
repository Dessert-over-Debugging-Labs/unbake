from tests.evaluation.conftest import make_candidate
from unbake.evaluation.claims import generate_claims
from unbake.evaluation.ids import assign_candidate_ids
from unbake.evaluation.omissions import detect_omissions
from unbake.models import BlindExtraction, DescriptionFacts, Fact


def _claims(*names):
    c = assign_candidate_ids(make_candidate([], ingredients=[(n, None) for n in names]))
    return generate_claims(c)


def _blind(*facts):
    return BlindExtraction(audio_facts=list(facts))


def test_복합_표기는_쪼개서_빠진_것만_누락():
    fact = Fact(kind="INGREDIENT", name="마요네즈, 치즈, 파슬리", text="자막")
    out = detect_omissions(_claims("마요네즈", "치즈"), DescriptionFacts(), _blind(fact))
    assert len(out) == 1
    assert out[0].text.startswith("파슬리")


def test_전부_알면_누락_아님():
    fact = Fact(kind="INGREDIENT", name="버터, 스위트콘", text="자막")
    out = detect_omissions(_claims("버터", "스위트콘"), DescriptionFacts(), _blind(fact))
    assert out == []


def test_단일_미지_재료는_누락():
    fact = Fact(kind="INGREDIENT", name="대파", text="대파 (자막)")
    out = detect_omissions(_claims("두부"), DescriptionFacts(), _blind(fact))
    assert len(out) == 1
