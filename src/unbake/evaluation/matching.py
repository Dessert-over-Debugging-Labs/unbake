"""세부 단계 ↔ action 매칭 검증과 대단계 롤업 — 전부 결정적 코드.

의미 매칭은 LLM이 제안하고, 여기서 참조 존재·연속성·중복·순서를 검증한다.
순서 비교는 매칭된 action span 기준이며, 겹치는 span은 자동 역순 처리하지 않는다
(명백히 분리된 역순만 충돌로 본다).
"""

from dataclasses import dataclass, field

from unbake.models import (
    RecipeCandidate,
    StepRollup,
    StepRollupStatus,
    SubStepMapping,
    SubStepMappingStatus,
    ValidationIssue,
    VideoAction,
)

Span = tuple[int, int]  # half-open [startMs, endMs)


@dataclass
class MatchingOutcome:
    mappings: list[SubStepMapping] = field(default_factory=list)
    rollups: list[StepRollup] = field(default_factory=list)
    step_spans: dict[str, Span | None] = field(default_factory=dict)  # temporal 입력
    issues: list[ValidationIssue] = field(default_factory=list)


def _clearly_before(later: Span, earlier: Span) -> bool:
    """later가 earlier보다 명백히 앞(분리된 역순)인가. 겹침은 충돌이 아니다."""
    return later[1] <= earlier[0]


def validate_and_rollup(
    candidate: RecipeCandidate,
    actions: list[VideoAction],
    proposals: list[SubStepMapping],
) -> MatchingOutcome:
    """recovery가 subStepId 전수성을 보장한 제안을 받아 검증·롤업한다."""
    out = MatchingOutcome()
    action_pos = {a.action_id: i for i, a in enumerate(actions)}
    action_span = {a.action_id: (a.start_ms, a.end_ms) for a in actions}
    proposal_by_id = {m.sub_step_id: m for m in proposals}

    # 전역 세부 단계 순서 (대단계 순서 → 세부 단계 순서)
    global_order: list[str] = [
        sub.sub_step_id for _step, sub in candidate.iter_sub_steps() if sub.sub_step_id
    ]
    global_index = {sid: i for i, sid in enumerate(global_order)}

    # 1) 개별 매핑 검증
    validated: dict[str, SubStepMapping] = {}
    for sid in global_order:
        m = proposal_by_id[sid].model_copy(deep=True)

        # 유령 action 참조는 기록 후 제거
        kept = []
        for aid in m.action_ids:
            if aid in action_pos:
                kept.append(aid)
            else:
                m.violations.append("ghost_action_ref")
                out.issues.append(
                    ValidationIssue(
                        code="GHOST_REF", ref=sid, message=f"존재하지 않는 action 참조: {aid}"
                    )
                )
        m.action_ids = kept

        if m.status == SubStepMappingStatus.MATCHED and not m.action_ids:
            # 근거 없는 MATCHED는 UNMATCHED로 강등 (보수적)
            m.violations.append("matched_without_action")
            m.status = SubStepMappingStatus.UNMATCHED
        elif m.status != SubStepMappingStatus.MATCHED and m.action_ids:
            m.violations.append("action_on_non_matched")
            m.action_ids = []

        # 연속성 — 한 세부 단계의 action들은 B의 순서상 연속이어야 한다
        if len(m.action_ids) > 1:
            positions = sorted(action_pos[a] for a in m.action_ids)
            if positions != list(range(positions[0], positions[-1] + 1)):
                m.violations.append("non_contiguous")
            m.action_ids = sorted(m.action_ids, key=lambda a: action_pos[a])

        validated[sid] = m

    # 2) action 공유 — 기본 금지, 전역 순서상 인접한 세부 단계 간에만 flag로 허용
    users: dict[str, list[str]] = {}
    for sid in global_order:
        for aid in validated[sid].action_ids:
            users.setdefault(aid, []).append(sid)
    for aid, sids in users.items():
        if len(sids) < 2:
            continue
        indices = sorted(global_index[s] for s in sids)
        adjacent = indices == list(range(indices[0], indices[-1] + 1))
        flag = "shared_action_adjacent" if adjacent else "shared_action_nonadjacent"
        for sid in sids:
            validated[sid].violations.append(flag)
        if not adjacent:
            out.issues.append(
                ValidationIssue(
                    code="SHARED_ACTION",
                    ref=aid,
                    message=f"비인접 세부 단계들이 action을 공유: {', '.join(sids)}",
                )
            )

    def sub_span(sid: str) -> Span | None:
        m = validated[sid]
        if m.status != SubStepMappingStatus.MATCHED or not m.action_ids:
            return None
        spans = [action_span[a] for a in m.action_ids]
        return (min(s for s, _ in spans), max(e for _, e in spans))

    # 3) 순서 검증 2층 + 롤업
    prev_step_span: Span | None = None
    for step in candidate.steps:
        sids = [s.sub_step_id for s in step.sub_steps if s.sub_step_id]
        subs = [validated[sid] for sid in sids]
        order_conflict = False

        # 대단계 안 세부 단계 간 순서
        prev_sub_span: Span | None = None
        for sid in sids:
            span = sub_span(sid)
            if span is None:
                continue
            if prev_sub_span is not None and _clearly_before(span, prev_sub_span):
                validated[sid].violations.append("order_conflict_within_step")
                order_conflict = True
            prev_sub_span = span

        # 대단계 span (매칭된 세부 단계들의 전체 span)
        matched_spans = [sp for sp in (sub_span(sid) for sid in sids) if sp is not None]
        step_span: Span | None = None
        if matched_spans:
            step_span = (min(s for s, _ in matched_spans), max(e for _, e in matched_spans))
        out.step_spans[step.step_id or ""] = step_span

        # 대단계 간 순서 — 뒤 단계가 앞 단계보다 명백히 앞이면 뒤 단계에 충돌 표시
        if step_span is not None:
            if prev_step_span is not None and _clearly_before(step_span, prev_step_span):
                order_conflict = True
            prev_step_span = step_span

        matched = sum(1 for m in subs if m.status == SubStepMappingStatus.MATCHED)
        unmatched = sum(1 for m in subs if m.status == SubStepMappingStatus.UNMATCHED)
        unobservable = sum(1 for m in subs if m.status == SubStepMappingStatus.UNOBSERVABLE)
        observable = matched + unmatched

        if order_conflict:
            status = StepRollupStatus.ORDER_CONFLICT
        elif observable == 0:
            # 관찰 불가 세부 단계뿐 — 패널티 없음
            status = StepRollupStatus.MATCHED
        elif unmatched == 0:
            status = StepRollupStatus.MATCHED
        elif matched > 0:
            status = StepRollupStatus.PARTIAL
        else:
            status = StepRollupStatus.UNMATCHED

        out.rollups.append(
            StepRollup(
                step_id=step.step_id or "",
                status=status,
                matched_count=matched,
                unmatched_count=unmatched,
                unobservable_count=unobservable,
                unobservable_only=(observable == 0 and unobservable > 0),
            )
        )

    out.mappings = [validated[sid] for sid in global_order]
    return out
