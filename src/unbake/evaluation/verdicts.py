"""판정 조인 — source별 verdict를 코드 규칙으로 fusedVerdict·severity로 결정한다.

source 간 충돌은 판정 LLM이 아니라 여기서 발견한다 (source 격벽 — docs/decisions/001).
"""

from unbake.models import (
    Claim,
    ClaimAspect,
    ClaimEvaluation,
    ClaimSourceJudgement,
    FusedVerdict,
    Severity,
    Source,
    SourceVerdict,
)


def fuse_verdicts(by_source: dict[Source, ClaimSourceJudgement]) -> FusedVerdict:
    """조인 규칙 (golden test로 고정):

    SUPPORTED와 CONTRADICTED 공존 → CONFLICT (source끼리 충돌)
    그 외 우선순위: CONTRADICTED > SUPPORTED > UNKNOWN
    분량은 설명란에만 명시돼도 SUPPORTED 가능하다 (docs/architecture.md).
    """
    verdicts = {j.verdict for j in by_source.values()}
    has_supported = SourceVerdict.SUPPORTED in verdicts
    has_contradicted = SourceVerdict.CONTRADICTED in verdicts
    if has_supported and has_contradicted:
        return FusedVerdict.CONFLICT
    if has_contradicted:
        return FusedVerdict.CONTRADICTED
    if has_supported:
        return FusedVerdict.SUPPORTED
    return FusedVerdict.UNKNOWN


# severity 표 — CONTRADICTED/CONFLICT에만 부여. 임계값 보정 전의 보수적 초기값이며
# 바꿀 때는 golden test와 함께 바꾼다.
_SEVERITY_TABLE: dict[tuple[ClaimAspect, FusedVerdict], Severity] = {
    (ClaimAspect.EXISTENCE, FusedVerdict.CONTRADICTED): Severity.CRITICAL,  # 환각 재료
    (ClaimAspect.EXISTENCE, FusedVerdict.CONFLICT): Severity.MAJOR,
    (ClaimAspect.AMOUNT, FusedVerdict.CONTRADICTED): Severity.MAJOR,
    (ClaimAspect.AMOUNT, FusedVerdict.CONFLICT): Severity.MAJOR,
}


def severity_for(claim: Claim, fused: FusedVerdict) -> Severity | None:
    return _SEVERITY_TABLE.get((claim.aspect, fused))


def join_claim_evaluations(
    claims: list[Claim],
    judgements_by_source: dict[Source, list[ClaimSourceJudgement]],
) -> list[ClaimEvaluation]:
    """source별 판정 결과를 claimId로 조인한다.

    호출 전에 recovery 단계가 각 source 응답의 전수성(모든 claimId 정확히 1회)을
    보장했다고 가정한다 — 여기서는 순수 조인·fuse만 한다.
    """
    indexed: dict[Source, dict[str, ClaimSourceJudgement]] = {
        source: {j.claim_id: j for j in items} for source, items in judgements_by_source.items()
    }
    evaluations = []
    for claim in claims:
        by_source = {
            source: index[claim.claim_id]
            for source, index in indexed.items()
            if claim.claim_id in index
        }
        fused = fuse_verdicts(by_source)
        evaluations.append(
            ClaimEvaluation(
                claim_id=claim.claim_id,
                by_source=by_source,
                fused=fused,
                severity=severity_for(claim, fused),
            )
        )
    return evaluations
