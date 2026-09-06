"""대단계 단위 temporal 평가 — A의 timestamp vs 매칭된 B action들의 span.

시간은 정수 ms + half-open [startMs, endMs). 잘못된 구간은 조용히 보정하지 않고
ValidationIssue로 기록한다. tIoU는 진단용이며 단독 gate로 쓰지 않는다.
"""

import statistics
from dataclasses import dataclass, field

from unbake.models import RecipeCandidate, TemporalEvaluation, ValidationIssue

# float 직렬화 자릿수 고정 (재현성)
_ROUND = 4

# 임시 보수 규칙 — 사람 수정 데이터로 보정하기 전의 잠정값 (docs/architecture.md)
SUSPECT_TIOU_DEFAULT = 0.3


@dataclass
class TemporalOutcome:
    evaluations: list[TemporalEvaluation] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    suspect_count: int = 0  # 시간이 안 맞는 의심 구간 수
    unverified_count: int = 0  # 영상으로 확인 못 한 구간 수
    median_iou: float | None = None


def evaluate_temporal(
    candidate: RecipeCandidate,
    step_spans: dict[str, tuple[int, int] | None],
    suspect_tiou: float = SUSPECT_TIOU_DEFAULT,
) -> TemporalOutcome:
    out = TemporalOutcome()
    ious: list[float] = []

    for step in candidate.steps:
        sid = step.step_id or ""
        start, end = step.start_ms, step.end_ms
        ts_valid = start is not None and end is not None

        if (start is None) != (end is None):
            out.issues.append(
                ValidationIssue(code="RANGE_HALF_MISSING", ref=sid, message="start/end 한쪽만 존재")
            )
            ts_valid = False
        if ts_valid and end <= start:
            out.issues.append(
                ValidationIssue(
                    code="RANGE_INVALID", ref=sid, message=f"end({end}) <= start({start})"
                )
            )
            ts_valid = False
        if ts_valid and candidate.duration_ms is not None and end > candidate.duration_ms:
            out.issues.append(
                ValidationIssue(
                    code="BEYOND_DURATION",
                    ref=sid,
                    message=f"end({end}) > durationMs({candidate.duration_ms})",
                )
            )
            # 영상 길이 밖 구간은 critical defect 후보지만 지표 계산은 계속한다

        span = step_spans.get(sid)
        ev = TemporalEvaluation(
            step_id=sid,
            matched=span is not None,
            candidate_start_ms=start if ts_valid else None,
            candidate_end_ms=end if ts_valid else None,
            action_span_start_ms=span[0] if span else None,
            action_span_end_ms=span[1] if span else None,
        )

        if span is not None and ts_valid:
            inter = max(0, min(end, span[1]) - max(start, span[0]))
            union = (end - start) + (span[1] - span[0]) - inter
            ev.intersection_ms = inter
            ev.union_ms = union
            ev.temporal_iou = round(inter / union, _ROUND) if union > 0 else 0.0
            ev.start_delta_ms = start - span[0]
            ev.end_delta_ms = end - span[1]
            ious.append(ev.temporal_iou)
            if ev.temporal_iou < suspect_tiou:
                out.suspect_count += 1
        else:
            # 매칭된 동작이 없거나 timestamp가 유효하지 않으면 검증 불가 구간
            out.unverified_count += 1

        out.evaluations.append(ev)

    if ious:
        out.median_iou = round(statistics.median(ious), _ROUND)
    return out
