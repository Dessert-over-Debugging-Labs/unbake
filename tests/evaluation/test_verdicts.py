"""fuse·severity 규칙 golden test — 표를 바꾸면 이 테스트도 함께 바꾼다."""

import pytest

from unbake.evaluation.verdicts import fuse_verdicts, join_claim_evaluations, severity_for
from unbake.models import (
    Claim,
    ClaimAspect,
    ClaimSourceJudgement,
    FusedVerdict,
    Severity,
    Source,
    SourceVerdict,
)


def _j(verdict: SourceVerdict) -> ClaimSourceJudgement:
    return ClaimSourceJudgement(claim_id="c1", verdict=verdict)


# (desc, audio, visual) → fused — 전 조합 golden
FUSE_GOLDEN = [
    (("SUPPORTED", "SUPPORTED", "SUPPORTED"), FusedVerdict.SUPPORTED),
    (("SUPPORTED", "UNKNOWN", "UNKNOWN"), FusedVerdict.SUPPORTED),  # 설명란 단독 SUPPORTED 인정
    (("UNKNOWN", "UNKNOWN", "UNKNOWN"), FusedVerdict.UNKNOWN),
    (("CONTRADICTED", "UNKNOWN", "UNKNOWN"), FusedVerdict.CONTRADICTED),
    (("CONTRADICTED", "CONTRADICTED", "UNKNOWN"), FusedVerdict.CONTRADICTED),
    (("SUPPORTED", "CONTRADICTED", "UNKNOWN"), FusedVerdict.CONFLICT),  # source끼리 충돌
    (("SUPPORTED", "CONTRADICTED", "SUPPORTED"), FusedVerdict.CONFLICT),
    (("UNKNOWN", "SUPPORTED", "CONTRADICTED"), FusedVerdict.CONFLICT),
]


@pytest.mark.parametrize("verdicts,expected", FUSE_GOLDEN)
def test_fuse_전조합(verdicts, expected):
    by_source = {
        source: _j(SourceVerdict(v))
        for source, v in zip(
            [Source.DESCRIPTION, Source.AUDIO, Source.VISUAL], verdicts, strict=True
        )
    }
    assert fuse_verdicts(by_source) == expected


def test_fuse_일부_source만_있어도_동작():
    assert fuse_verdicts({Source.AUDIO: _j(SourceVerdict.SUPPORTED)}) == FusedVerdict.SUPPORTED
    assert fuse_verdicts({}) == FusedVerdict.UNKNOWN


SEVERITY_GOLDEN = [
    (ClaimAspect.EXISTENCE, FusedVerdict.CONTRADICTED, Severity.CRITICAL),  # 환각 재료
    (ClaimAspect.EXISTENCE, FusedVerdict.CONFLICT, Severity.MAJOR),
    (ClaimAspect.AMOUNT, FusedVerdict.CONTRADICTED, Severity.MAJOR),
    (ClaimAspect.AMOUNT, FusedVerdict.CONFLICT, Severity.MAJOR),
    (ClaimAspect.EXISTENCE, FusedVerdict.SUPPORTED, None),
    (ClaimAspect.AMOUNT, FusedVerdict.UNKNOWN, None),
]


@pytest.mark.parametrize("aspect,fused,expected", SEVERITY_GOLDEN)
def test_severity_표(aspect, fused, expected):
    claim = Claim(claim_id="c1", aspect=aspect, subject="소금", text="t")
    assert severity_for(claim, fused) == expected


def test_join은_claimId로_조인한다():
    claims = [
        Claim(claim_id="c1", aspect=ClaimAspect.EXISTENCE, subject="소금", text="t"),
        Claim(claim_id="c2", aspect=ClaimAspect.AMOUNT, subject="소금", value="1큰술", text="t"),
    ]
    by_source = {
        Source.DESCRIPTION: [
            ClaimSourceJudgement(claim_id="c1", verdict=SourceVerdict.SUPPORTED),
            ClaimSourceJudgement(claim_id="c2", verdict=SourceVerdict.CONTRADICTED),
        ],
        Source.AUDIO: [
            ClaimSourceJudgement(claim_id="c1", verdict=SourceVerdict.UNKNOWN),
            ClaimSourceJudgement(claim_id="c2", verdict=SourceVerdict.SUPPORTED),
        ],
    }
    evals = join_claim_evaluations(claims, by_source)
    assert evals[0].fused == FusedVerdict.SUPPORTED
    assert evals[0].severity is None
    assert evals[1].fused == FusedVerdict.CONFLICT
    assert evals[1].severity == Severity.MAJOR
    assert evals[1].by_source[Source.AUDIO].verdict == SourceVerdict.SUPPORTED
