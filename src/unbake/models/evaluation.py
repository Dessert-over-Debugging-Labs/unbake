"""평가 산출물 계약 — EvaluationResult와 그 구성요소.

상태값 표기 규칙: 새 값을 추가하면 반드시 `영어 (한글 핵심 구절)` 주석을 병기한다.
0~100 종합 점수는 만들지 않는다 — 서로 다른 오류가 평균으로 상쇄되기 때문 (docs/decisions/).
"""

from enum import StrEnum

from unbake.models.base import ApiModel


class Source(StrEnum):
    DESCRIPTION = "DESCRIPTION"  # 설명란
    AUDIO = "AUDIO"  # 음성
    VISUAL = "VISUAL"  # 화면


class SourceVerdict(StrEnum):
    SUPPORTED = "SUPPORTED"  # 근거 있음
    CONTRADICTED = "CONTRADICTED"  # 모순 — A가 틀린 듯
    UNKNOWN = "UNKNOWN"  # 근거 없음


class FusedVerdict(StrEnum):
    SUPPORTED = "SUPPORTED"  # 근거 있음
    CONTRADICTED = "CONTRADICTED"  # 모순 — A가 틀린 듯
    UNKNOWN = "UNKNOWN"  # 근거 없음
    CONFLICT = "CONFLICT"  # source끼리 충돌


class Severity(StrEnum):
    CRITICAL = "CRITICAL"  # 그대로 나가면 레시피가 틀리는 수준
    MAJOR = "MAJOR"  # 사람 확인 필요
    MINOR = "MINOR"  # 참고


class ClaimSourceJudgement(ApiModel):
    """판정 LLM이 source 하나에 대해 내린 claim 판정."""

    claim_id: str
    verdict: SourceVerdict
    fact_refs: list[str] = []  # 근거 factId — 코드가 존재 여부를 검사한다
    observed_value: str | None = None  # CONTRADICTED일 때 source가 제시한 값
    reason: str | None = None


class ClaimEvaluation(ApiModel):
    """claim 하나의 최종 평가 — source별 판정 + 코드 조인 결과."""

    claim_id: str
    by_source: dict[Source, ClaimSourceJudgement]
    fused: FusedVerdict  # 최종 판정 — 코드 규칙으로 결정
    severity: Severity | None = None  # 심각도 — CONTRADICTED/CONFLICT에만 부여


class SubStepMappingStatus(StrEnum):
    MATCHED = "MATCHED"  # 영상 동작과 일치
    UNMATCHED = "UNMATCHED"  # 대응 동작 없음
    UNOBSERVABLE = "UNOBSERVABLE"  # 관찰 불가 — 대기·방치형 (패널티 제외)


class SubStepMapping(ApiModel):
    """세부 단계 ↔ action 매칭 결과 (LLM 제안 + 코드 검증)."""

    sub_step_id: str
    status: SubStepMappingStatus
    action_ids: list[str] = []  # MATCHED일 때 근거 action — B의 순서상 연속이어야 함
    violations: list[str] = []  # 코드 검증에서 발견한 위반 (non_contiguous 등)


class StepRollupStatus(StrEnum):
    MATCHED = "MATCHED"  # 세부 단계 전부 일치
    PARTIAL = "PARTIAL"  # 일부만 일치
    UNMATCHED = "UNMATCHED"  # 일치하는 세부 단계 없음
    ORDER_CONFLICT = "ORDER_CONFLICT"  # 순서 충돌


class StepRollup(ApiModel):
    """대단계 상태 — 코드 롤업. LLM은 대단계를 직접 매칭하지 않는다."""

    step_id: str
    status: StepRollupStatus
    matched_count: int = 0
    unmatched_count: int = 0
    unobservable_count: int = 0
    unobservable_only: bool = False  # 관찰 가능한 세부 단계가 없는 대단계 (패널티 없음)


class TemporalEvaluation(ApiModel):
    """대단계 단위 시간 평가 — A의 timestamp vs 매칭된 B action들의 span.

    시간은 정수 ms, half-open [startMs, endMs). tIoU 등 파생 지표만 float.
    """

    step_id: str
    matched: bool  # 대응 영상 동작 존재 여부
    candidate_start_ms: int | None = None
    candidate_end_ms: int | None = None
    action_span_start_ms: int | None = None
    action_span_end_ms: int | None = None
    intersection_ms: int | None = None  # 재현성 위해 원시값도 보존
    union_ms: int | None = None
    temporal_iou: float | None = None  # 두 구간의 겹침 정도
    start_delta_ms: int | None = None  # candidate - actionSpan
    end_delta_ms: int | None = None


class DetectedOmission(ApiModel):
    """누락 후보 — 설명란/B에는 있는데 A 레시피에는 없는 고신뢰 사실.

    초기에는 기록·표시만 하고 자동 탈락 기준으로 쓰지 않는다.
    """

    source: Source
    kind: str  # INGREDIENT | STEP | TIP
    text: str
    fact_refs: list[str] = []


class ValidationIssue(ApiModel):
    """결정적 검증에서 발견한 문제 — 조용히 보정하지 않고 기록한다."""

    code: str  # 예: RANGE_INVALID, BEYOND_DURATION, GHOST_REF
    ref: str | None = None  # 관련 ID (stepId / actionId / claimId …)
    message: str


class EvaluationSummary(ApiModel):
    """집계 — 종합 점수가 아니라 오류 종류별 카운트."""

    # 재료·분량 claim
    contradiction_count: int = 0  # 모순 claim 수
    source_conflict_count: int = 0  # source 충돌 claim 수
    unknown_claim_count: int = 0  # 근거 없는 claim 수
    # 대단계 기준
    matched_step_count: int = 0
    partial_step_count: int = 0
    unmatched_step_count: int = 0
    order_conflict_count: int = 0  # 순서 충돌 수
    # 세부 단계 기준
    unmatched_sub_step_count: int = 0
    unobservable_sub_step_count: int = 0  # 관찰 불가 — 패널티 아님
    # 영상 구간
    suspect_segment_count: int = 0  # 시간이 안 맞는 의심 구간 수
    suspect_segment_rate: float = 0.0
    unverified_segment_count: int = 0  # 영상으로 확인 못 한 구간 수
    unverified_segment_rate: float = 0.0
    median_temporal_iou: float | None = None  # 진단용 — 단독 gate로 쓰지 않는다
    # 누락
    omission_count: int = 0


class EvaluationResult(ApiModel):
    """영상 1건 평가의 최종 산출물."""

    evaluation_run_id: str
    video_id: str
    candidate_id: str | None = None
    revision_id: str | None = None
    claim_evaluations: list[ClaimEvaluation] = []
    sub_step_mappings: list[SubStepMapping] = []
    step_rollups: list[StepRollup] = []
    temporal_evaluations: list[TemporalEvaluation] = []
    detected_omissions: list[DetectedOmission] = []
    validation_issues: list[ValidationIssue] = []
    summary: EvaluationSummary = EvaluationSummary()
