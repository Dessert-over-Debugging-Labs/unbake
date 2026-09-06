"""③추출 + ④평가 오케스트레이션 — 영상 1건을 교차 검증 산출물로 만든다.

호출 구조 (영상 1개당 ~6회):
추출 A·B(영상, 비쌈) + 설명란 파싱 1 + 판정 3(source 격벽) + 매칭 1(텍스트, 저렴)
"""

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from unbake.evaluation.engine import compute_input_hash, evaluate_candidate
from unbake.evaluation.ids import (
    assign_blind_ids,
    assign_candidate_ids,
    assign_description_fact_ids,
)
from unbake.evaluation.ports import JudgePort, MatcherPort
from unbake.events import record_event
from unbake.extraction.ports import (
    BlindExtractorPort,
    DescriptionParserPort,
    GeneratorPort,
)
from unbake.models import (
    SCHEMA_VERSION,
    BlindExtraction,
    DescriptionFacts,
    EvaluationResult,
    RecipeCandidate,
    RunManifest,
)

logger = logging.getLogger(__name__)


@dataclass
class AnalysisArtifacts:
    candidate: RecipeCandidate
    description_facts: DescriptionFacts
    blind: BlindExtraction
    evaluation: EvaluationResult
    manifest: RunManifest


def analyze_and_evaluate(
    *,
    video_url: str,
    video_id: str,
    duration_ms: int | None,
    description: str,
    generator: GeneratorPort,
    blind_extractor: BlindExtractorPort,
    description_parser: DescriptionParserPort,
    judge: JudgePort,
    matcher: MatcherPort,
    run_id: str | None = None,
    on_evaluating: Callable[[RecipeCandidate, DescriptionFacts, BlindExtraction], None]
    | None = None,
) -> AnalysisArtifacts:
    run_id = run_id or f"run-{video_id}-{uuid.uuid4().hex[:8]}"

    # 추출 — A와 B는 서로의 존재를 모른다
    candidate, rec_a = generator.extract_candidate(video_url, video_id, duration_ms, description)
    logger.info(
        "추출 A 완료: 대단계 %d개, 재료 %d개", len(candidate.steps), len(candidate.ingredients)
    )
    blind, rec_b = blind_extractor.extract_facts(video_url, duration_ms)
    logger.info(
        "추출 B(blind) 완료: 음성 %d / 화면 %d / 동작 %d",
        len(blind.audio_facts),
        len(blind.visual_facts),
        len(blind.actions),
    )
    description_facts, rec_d = description_parser.parse(description)
    logger.info("설명란 파싱 완료: 사실 %d개", len(description_facts.facts))

    # ID 는 코드가 위치 기반으로 부여한다 — 산출물(candidate·blind·description-facts)에도 같은 ID 를
    # 실어 evaluation 의 s1/c1/a1/d1 참조가 파일만 보고 풀리게 한다. evaluate_candidate 는
    # 같은 규칙으로 다시 부여하므로(멱등) 값이 달라지지 않는다.
    candidate = assign_candidate_ids(candidate)
    description_facts = assign_description_fact_ids(description_facts)
    blind = assign_blind_ids(blind)

    if on_evaluating is not None:
        # 추출(analyzing)과 평가(evaluating)의 경계 — 상태 전이·run 기록은 호출자 몫
        on_evaluating(candidate, description_facts, blind)

    evaluation, judge_records = evaluate_candidate(
        run_id=run_id,
        candidate=candidate,
        description_facts=description_facts,
        blind=blind,
        judge=judge,
        matcher=matcher,
    )

    manifest = RunManifest(
        evaluation_run_id=run_id,
        schema_version=SCHEMA_VERSION,
        input_hash=compute_input_hash(candidate, description_facts, blind),
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        calls=[rec_a, rec_b, rec_d, *judge_records],
    )
    return AnalysisArtifacts(
        candidate=candidate,
        description_facts=description_facts,
        blind=blind,
        evaluation=evaluation,
        manifest=manifest,
    )


def save_artifacts(artifacts: AnalysisArtifacts, output_dir: Path) -> Path:
    """output/<videoId>/ 아래에 산출물 5종을 저장하고 ANALYZED 이벤트를 남긴다."""
    target = output_dir / artifacts.candidate.video_id
    target.mkdir(parents=True, exist_ok=True)
    files = {
        "candidate.json": artifacts.candidate,
        "description-facts.json": artifacts.description_facts,
        "blind.json": artifacts.blind,
        "evaluation.json": artifacts.evaluation,
        "manifest.json": artifacts.manifest,
    }
    for name, model in files.items():
        (target / name).write_text(
            json.dumps(model.dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    summary = artifacts.evaluation.summary
    record_event(
        output_dir,
        video_id=artifacts.candidate.video_id,
        event_type="ANALYZED",
        actor="agent",
        data={
            "runId": artifacts.manifest.evaluation_run_id,
            "inputHash": artifacts.manifest.input_hash,
            "contradictionCount": summary.contradiction_count,
            "sourceConflictCount": summary.source_conflict_count,
            "unknownClaimCount": summary.unknown_claim_count,
            "orderConflictCount": summary.order_conflict_count,
            "suspectSegmentCount": summary.suspect_segment_count,
            "unverifiedSegmentCount": summary.unverified_segment_count,
            "omissionCount": summary.omission_count,
        },
    )
    return target
