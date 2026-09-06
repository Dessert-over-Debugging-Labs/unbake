from tests.evaluation.conftest import make_candidate
from unbake.evaluation.claims import generate_claims
from unbake.evaluation.ids import assign_candidate_ids
from unbake.models import ClaimAspect


def _claims_for(candidate):
    return generate_claims(assign_candidate_ids(candidate))


def test_재료_존재와_분량은_별도_claim():
    claims = _claims_for(make_candidate([], ingredients=[("애호박", "1개")]))
    aspects = {(c.aspect, c.subject, c.value) for c in claims}
    assert (ClaimAspect.EXISTENCE, "애호박", None) in aspects
    assert (ClaimAspect.AMOUNT, "애호박", "1개") in aspects
    assert len(claims) == 2


def test_분량_없는_재료는_존재_claim만():
    claims = _claims_for(make_candidate([], ingredients=[("소금", None)]))
    assert len(claims) == 1
    assert claims[0].aspect == ClaimAspect.EXISTENCE


def test_영상참고_표기는_분량_claim_생성_안함():
    claims = _claims_for(make_candidate([], ingredients=[("고춧가루", "영상 참고")]))
    assert all(c.aspect == ClaimAspect.EXISTENCE for c in claims)


def test_세부단계_문장에서_분량_추출_및_subStepId_근거():
    c = make_candidate(
        [("절이기", (0, 12_000), ["애호박을 채 썬다", "소금 1작은술을 넣고 버무린다"])],
        ingredients=[("소금", None)],
    )
    claims = _claims_for(c)
    amount = [x for x in claims if x.aspect == ClaimAspect.AMOUNT]
    assert len(amount) == 1
    assert amount[0].subject == "소금"
    assert amount[0].value == "1작은술"
    assert "s1b" in amount[0].evidence_refs


def test_동일_claim은_병합되고_evidence가_합쳐진다():
    c = make_candidate(
        [("양념", (0, 5_000), ["설탕 2큰술을 넣는다"])],
        ingredients=[("설탕", "2큰술")],
    )
    claims = _claims_for(c)
    amount = [x for x in claims if x.aspect == ClaimAspect.AMOUNT]
    assert len(amount) == 1
    assert set(amount[0].evidence_refs) == {"i1", "s1a"}


def test_claimId는_c접두_일련번호():
    claims = _claims_for(make_candidate([], ingredients=[("두부", "1모"), ("대파", None)]))
    assert [c.claim_id for c in claims] == [f"c{i}" for i in range(1, len(claims) + 1)]
