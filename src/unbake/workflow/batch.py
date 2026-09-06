"""배치 오케스트레이션 — ①탐색 → ②필터 → ③추출·④평가를 상태머신 위에서 돌린다.

상태는 2층으로 추적한다 (docs/architecture.md):
- workflow 상태: queued → analyzing → evaluating → pending_review (실패는 *_failed)
- evaluation run: pending → running → succeeded/failed + artifact 경로·manifest
"""

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from unbake.adapters.sqlite import store as S
from unbake.adapters.sqlite.store import Store
from unbake.adapters.youtube.discover import discover
from unbake.evaluation.engine import compute_input_hash
from unbake.filtering.domain import DomainJudgePort
from unbake.filtering.filter import run_filter
from unbake.workflow.analyze import analyze_and_evaluate, save_artifacts
from unbake.workflow.gate import run_domain_gate

logger = logging.getLogger(__name__)


@dataclass
class AnalysisPorts:
    """③추출·④평가에 필요한 port 묶음 — 조립은 호출자(CLI/서버)가 config로 한다."""

    generator: object
    blind_extractor: object
    description_parser: object
    judge: object
    matcher: object


@dataclass
class BatchReport:
    discovered: int = 0
    queued: list[dict] = field(default_factory=list)
    analyzed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    off_domain: list[tuple[str, str]] = field(default_factory=list)  # 도메인 게이트 탈락

    def summary_line(self) -> str:
        return (
            f"탐색 {self.discovered}건 / 큐 {len(self.queued)}건 / "
            f"도메인 탈락 {len(self.off_domain)}건 / "
            f"분석 성공 {len(self.analyzed)}건 / 실패 {len(self.failed)}건"
        )


def discover_and_filter(
    *,
    api_key: str,
    store: Store,
    judge: Callable[[str], dict],
    n_searches: int = 5,
    top_n: int = 15,
    seed: int | None = None,
    target: int = 50,
) -> tuple[int, list[dict]]:
    """①+② — 신규 후보를 이력에 등록하고 상위 N을 queued로. (탐색 수, 통과 목록) 반환."""
    candidates = discover(
        api_key, store, store, n_searches=n_searches, seed=seed, target=target
    )
    passed = run_filter(candidates, judge=judge, history=store, top_n=top_n)
    logger.info("탐색 %d건 → 필터 통과 %d건", len(candidates), len(passed))
    return len(candidates), passed


def analyze_queued(
    *,
    store: Store,
    output_dir: Path,
    ports: AnalysisPorts,
    meta_fetcher: Callable[[str], dict | None],
    count: int = 3,
    domain_judge: DomainJudgePort | None = None,
) -> BatchReport:
    """queued 상위 count건을 (도메인 게이트 →) 추출·평가해 pending_review까지 보낸다.

    domain_judge가 있으면 영상 호출 전에 메타만으로 요리 영상인지 거른다 — 탈락은
    filtered_out(사유 off_domain), 판정 실패는 analyze_failed. None이면 게이트 없이 진행.
    """
    report = BatchReport()
    rows = store.list_by_state(S.QUEUED)[:count]

    for row in rows:
        vid = row["video_id"]
        meta = meta_fetcher(vid) or {}
        duration_ms = meta.get("durationMs") or row["duration_ms"] or None
        description = meta.get("description", "")

        if domain_judge is not None:
            try:
                gate = run_domain_gate(
                    domain_judge, video_id=vid,
                    title=meta.get("title") or row["title"] or "",
                    channel_title=meta.get("channelTitle") or row["channel_title"] or "",
                    duration_ms=duration_ms, description=description, output_dir=output_dir,
                )
            except Exception as exc:  # 판정 실패는 통과가 아니다 — 실패로 기록하고 다음 건
                reason = f"domain_check_error: {type(exc).__name__}: {exc}"[:300]
                store.transition(vid, S.ANALYZE_FAILED, reason=reason)
                report.failed.append((vid, reason))
                logger.warning("[%s] 도메인 게이트 오류: %s", vid, reason)
                continue
            if not gate.passed:
                store.transition(vid, S.FILTERED_OUT, reason=gate.reason)
                report.off_domain.append((vid, gate.reason))
                continue

        store.transition(vid, S.ANALYZING)
        run_id = f"run-{vid}-{uuid.uuid4().hex[:8]}"
        reached_evaluation = False

        def on_evaluating(candidate, description_facts, blind, *, _vid=vid, _run_id=run_id):
            """추출 끝 — candidate를 즉시 저장하고 run을 열어 평가 실패도 추적한다."""
            nonlocal reached_evaluation
            target = output_dir / _vid
            target.mkdir(parents=True, exist_ok=True)
            (target / "candidate.json").write_text(
                json.dumps(candidate.dump(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            revision_id = f"rev-{_vid}-orig"
            if store.get_revision(revision_id) is None:
                store.add_revision(
                    revision_id, _vid,
                    artifact_path=f"{_vid}/candidate.json", source="extraction",
                )
            store.create_run(
                _run_id, _vid, revision_id,
                input_hash=compute_input_hash(candidate, description_facts, blind),
            )
            store.transition_run(_run_id, S.RUN_RUNNING)
            store.transition(_vid, S.EVALUATING)
            reached_evaluation = True

        try:
            artifacts = analyze_and_evaluate(
                video_url=f"https://www.youtube.com/watch?v={vid}",
                video_id=vid,
                duration_ms=duration_ms,
                description=description,
                generator=ports.generator,
                blind_extractor=ports.blind_extractor,
                description_parser=ports.description_parser,
                judge=ports.judge,
                matcher=ports.matcher,
                run_id=run_id,
                on_evaluating=on_evaluating,
            )
            target = save_artifacts(artifacts, output_dir)
            if meta:
                (target / "meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            store.transition_run(
                run_id, S.RUN_SUCCEEDED,
                artifact_path=f"{vid}/evaluation.json",
                manifest_json=json.dumps(artifacts.manifest.dump(), ensure_ascii=False),
            )
            store.transition(vid, S.PENDING_REVIEW)
            report.analyzed.append(vid)
            logger.info("[%s] 분석·평가 완료 → pending_review", vid)
        except Exception as exc:  # 한 건의 실패가 배치를 죽이지 않는다 (과거 실측)
            reason = f"{type(exc).__name__}: {exc}"[:300]
            if reached_evaluation:
                store.transition_run(run_id, S.RUN_FAILED)
                store.transition(vid, S.EVALUATION_FAILED, reason=reason)
            else:
                store.transition(vid, S.ANALYZE_FAILED, reason=reason)
            report.failed.append((vid, reason))
            logger.warning("[%s] 실패 (%s 단계): %s", vid,
                           "평가" if reached_evaluation else "추출", reason)

    return report
