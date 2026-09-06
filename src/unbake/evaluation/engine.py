"""평가 엔진 — 영상 1건의 교차 검증을 오케스트레이션한다.

ID 부여 → claim 생성 → source별 판정(격벽 호출·복구) → 코드 조인 →
매칭 검증·롤업 → temporal → 누락 → summary. LLM 호출 이력을 전부 반환한다.
"""

import hashlib
import json

from unbake.evaluation.claims import generate_claims
from unbake.evaluation.ids import (
    assign_blind_ids,
    assign_candidate_ids,
    assign_description_fact_ids,
)
from unbake.evaluation.matching import validate_and_rollup
from unbake.evaluation.omissions import detect_omissions
from unbake.evaluation.ports import JudgePort, MatcherPort
from unbake.evaluation.recovery import run_batch_with_recovery
from unbake.evaluation.temporal import SUSPECT_TIOU_DEFAULT, evaluate_temporal
from unbake.evaluation.verdicts import join_claim_evaluations
from unbake.models import (
    SCHEMA_VERSION,
    BlindExtraction,
    ClaimSourceJudgement,
    DescriptionFacts,
    EvaluationResult,
    EvaluationSummary,
    FusedVerdict,
    LlmCallRecord,
    RecipeCandidate,
    Source,
    SourceFacts,
    StepRollupStatus,
    SubStepMappingStatus,
    ValidationIssue,
)


def compute_input_hash(
    candidate: RecipeCandidate,
    description_facts: DescriptionFacts,
    blind: BlindExtraction,
) -> str:
    """입력 snapshot 해시 — artifact 재사용·재현성 추적의 키."""
    payload = json.dumps(
        {
            "schema": SCHEMA_VERSION,
            "candidate": candidate.dump(),
            "description": description_facts.dump(),
            "blind": blind.dump(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def evaluate_candidate(
    *,
    run_id: str,
    candidate: RecipeCandidate,
    description_facts: DescriptionFacts,
    blind: BlindExtraction,
    judge: JudgePort,
    matcher: MatcherPort,
    revision_id: str | None = None,
    suspect_tiou: float = SUSPECT_TIOU_DEFAULT,
    max_structural_retries: int = 2,
) -> tuple[EvaluationResult, list[LlmCallRecord]]:
    # 0) ID는 코드가 부여한다
    candidate = assign_candidate_ids(candidate)
    description_facts = assign_description_fact_ids(description_facts)
    blind = assign_blind_ids(blind)

    claims = generate_claims(candidate)
    claim_ids = [c.claim_id for c in claims]
    records: list[LlmCallRecord] = []
    issues: list[ValidationIssue] = []

    # B action 범위 검증 — 프롬프트가 '영상 길이 이내'를 지시해도 위반은 실제로 발생한다
    # (2026-09-05 smoke: 76초 영상에 100.5초 action). 조용히 보정하지 않고 기록한다.
    for action in blind.actions:
        if action.end_ms <= action.start_ms:
            issues.append(
                ValidationIssue(
                    code="ACTION_RANGE_INVALID",
                    ref=action.action_id,
                    message=f"end({action.end_ms}) <= start({action.start_ms})",
                )
            )
        elif candidate.duration_ms is not None and action.end_ms > candidate.duration_ms:
            issues.append(
                ValidationIssue(
                    code="ACTION_BEYOND_DURATION",
                    ref=action.action_id,
                    message=(
                        f"action end({action.end_ms})가 영상 길이({candidate.duration_ms}) 초과"
                        " — 이 action이 매칭된 구간의 temporal 지표는 신뢰 불가"
                    ),
                )
            )

    # 1) source별 판정 — 격벽 호출, source당 1회 + 복구
    source_bundles = {
        Source.DESCRIPTION: description_facts.facts,
        Source.AUDIO: blind.audio_facts,
        Source.VISUAL: blind.visual_facts,
    }
    judgements_by_source: dict[Source, list[ClaimSourceJudgement]] = {}
    for source, facts in source_bundles.items():
        bundle = SourceFacts(source=source.value, facts=facts)
        items, call_records = run_batch_with_recovery(
            purpose=f"judge_{source.value.lower()}",
            expected_ids=claim_ids,
            call=lambda req, _b=bundle: judge.judge(claims, _b, req),
            key_fn=lambda j: j.claim_id,
            max_structural_retries=max_structural_retries,
        )
        records.extend(call_records)
        # 유령 fact 참조는 기록 후 제거
        fact_ids = {f.fact_id for f in facts if f.fact_id}
        for judgement in items:
            ghosts = [r for r in judgement.fact_refs if r not in fact_ids]
            if ghosts:
                judgement.fact_refs = [r for r in judgement.fact_refs if r in fact_ids]
                issues.append(
                    ValidationIssue(
                        code="GHOST_REF",
                        ref=judgement.claim_id,
                        message=(
                            f"{source.value} 판정이 존재하지 않는 fact 참조: {', '.join(ghosts)}"
                        ),
                    )
                )
        judgements_by_source[source] = items

    # 2) 코드 조인 — CONFLICT는 여기서 발견된다
    claim_evaluations = join_claim_evaluations(claims, judgements_by_source)

    # 3) 세부 단계 ↔ action 매칭 + 검증·롤업
    sub_step_ids = [sub.sub_step_id for _s, sub in candidate.iter_sub_steps() if sub.sub_step_id]
    proposals, match_records = run_batch_with_recovery(
        purpose="match_steps",
        expected_ids=sub_step_ids,
        call=lambda req: matcher.match(candidate, blind.actions, req),
        key_fn=lambda m: m.sub_step_id,
        max_structural_retries=max_structural_retries,
    )
    records.extend(match_records)
    matching = validate_and_rollup(candidate, blind.actions, proposals)
    issues.extend(matching.issues)

    # 4) temporal — 대단계 단위
    temporal = evaluate_temporal(candidate, matching.step_spans, suspect_tiou=suspect_tiou)
    issues.extend(temporal.issues)

    # 5) 누락 후보 — 기록만
    omissions = detect_omissions(claims, description_facts, blind)

    # 6) summary — 종합 점수 없이 오류 종류별 카운트
    step_total = len(candidate.steps)
    summary = EvaluationSummary(
        contradiction_count=sum(
            1 for e in claim_evaluations if e.fused == FusedVerdict.CONTRADICTED
        ),
        source_conflict_count=sum(1 for e in claim_evaluations if e.fused == FusedVerdict.CONFLICT),
        unknown_claim_count=sum(1 for e in claim_evaluations if e.fused == FusedVerdict.UNKNOWN),
        matched_step_count=sum(
            1 for r in matching.rollups if r.status == StepRollupStatus.MATCHED
        ),
        partial_step_count=sum(1 for r in matching.rollups if r.status == StepRollupStatus.PARTIAL),
        unmatched_step_count=sum(
            1 for r in matching.rollups if r.status == StepRollupStatus.UNMATCHED
        ),
        order_conflict_count=sum(
            1 for r in matching.rollups if r.status == StepRollupStatus.ORDER_CONFLICT
        ),
        unmatched_sub_step_count=sum(
            1 for m in matching.mappings if m.status == SubStepMappingStatus.UNMATCHED
        ),
        unobservable_sub_step_count=sum(
            1 for m in matching.mappings if m.status == SubStepMappingStatus.UNOBSERVABLE
        ),
        suspect_segment_count=temporal.suspect_count,
        suspect_segment_rate=round(temporal.suspect_count / step_total, 4) if step_total else 0.0,
        unverified_segment_count=temporal.unverified_count,
        unverified_segment_rate=(
            round(temporal.unverified_count / step_total, 4) if step_total else 0.0
        ),
        median_temporal_iou=temporal.median_iou,
        omission_count=len(omissions),
    )

    result = EvaluationResult(
        evaluation_run_id=run_id,
        video_id=candidate.video_id,
        candidate_id=candidate.candidate_id,
        revision_id=revision_id,
        claim_evaluations=claim_evaluations,
        sub_step_mappings=matching.mappings,
        step_rollups=matching.rollups,
        temporal_evaluations=temporal.evaluations,
        detected_omissions=omissions,
        validation_issues=issues,
        summary=summary,
    )
    return result, records
