"""CLI — `unbake evaluate <url>` 로 영상 1건을 교차 검증한다 (M1a smoke)."""

import argparse
import logging
import sys

from unbake.config import Config
from unbake.log import setup_cli_logging

logger = logging.getLogger(__name__)


def _cmd_evaluate(args: argparse.Namespace) -> int:
    from unbake.adapters.gemini import (
        GeminiBlindExtractor,
        GeminiClient,
        GeminiDescriptionParser,
        GeminiGenerator,
        GeminiJudge,
        GeminiMatcher,
    )
    from unbake.adapters.youtube.videos import get_video_meta
    from unbake.util import parse_video_id
    from unbake.workflow.analyze import analyze_and_evaluate, save_artifacts

    cfg = Config.load()
    cfg.require("gemini_api_key")

    video_id = parse_video_id(args.url)
    if not video_id:
        logger.error("유튜브 URL을 해석하지 못했습니다: %s", args.url)
        return 1

    duration_ms, description, meta = args.duration_ms, args.description, None
    if duration_ms is None or description is None:
        cfg.require("youtube_api_key")
        meta = get_video_meta(cfg.youtube_api_key, video_id)
        if meta is None:
            logger.error("영상을 찾을 수 없습니다: %s", video_id)
            return 1
        duration_ms = duration_ms if duration_ms is not None else meta["durationMs"]
        description = description if description is not None else meta["description"]
        logger.info("영상: %s (%s, %sms)", meta["title"], meta["channelTitle"], duration_ms)

    client = GeminiClient(cfg.gemini_api_key)
    models = cfg.models
    artifacts = analyze_and_evaluate(
        video_url=f"https://www.youtube.com/watch?v={video_id}",
        video_id=video_id,
        duration_ms=duration_ms,
        description=description,
        generator=GeminiGenerator(client, models.generator),
        blind_extractor=GeminiBlindExtractor(client, models.blind),
        description_parser=GeminiDescriptionParser(client, models.description),
        judge=GeminiJudge(client, models.judge),
        matcher=GeminiMatcher(client, models.matcher),
    )
    target = save_artifacts(artifacts, cfg.output_dir)
    if meta:
        import json

        (target / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    s = artifacts.evaluation.summary
    logger.info("저장: %s", target)
    logger.info(
        "claim %d건 — 모순 %d / 충돌 %d / 근거없음 %d",
        len(artifacts.evaluation.claim_evaluations),
        s.contradiction_count,
        s.source_conflict_count,
        s.unknown_claim_count,
    )
    logger.info(
        "대단계 %d개 — 일치 %d / 일부 %d / 불일치 %d / 순서충돌 %d",
        len(artifacts.evaluation.step_rollups),
        s.matched_step_count,
        s.partial_step_count,
        s.unmatched_step_count,
        s.order_conflict_count,
    )
    logger.info(
        "구간 — 의심 %d / 미검증 %d / 중앙값 tIoU %s",
        s.suspect_segment_count,
        s.unverified_segment_count,
        s.median_temporal_iou,
    )
    if s.omission_count:
        logger.info("누락 후보 %d건 (기록만 — 자동 탈락 아님)", s.omission_count)
    return 0


def _cmd_batch(args: argparse.Namespace) -> int:
    """①탐색+②필터 → ③추출·④평가 배치. 검수·등록은 대시보드에서 (사람 게이트)."""
    from unbake.adapters.gemini import (
        GeminiBlindExtractor,
        GeminiClient,
        GeminiDescriptionParser,
        GeminiGenerator,
        GeminiJudge,
        GeminiMatcher,
    )
    from unbake.adapters.gemini.filter_judge import GeminiFilterJudge
    from unbake.adapters.sqlite.store import Store
    from unbake.adapters.youtube.videos import get_video_meta
    from unbake.workflow.batch import AnalysisPorts, analyze_queued, discover_and_filter

    cfg = Config.load()
    cfg.require("gemini_api_key", "youtube_api_key")

    client = GeminiClient(cfg.gemini_api_key)
    models = cfg.models
    store = Store(cfg.db_path)
    try:
        discovered = 0
        if not args.skip_discover:
            discovered, passed = discover_and_filter(
                api_key=cfg.youtube_api_key,
                store=store,
                judge=GeminiFilterJudge(client, models.judge),
                n_searches=args.searches,
                top_n=args.top_n,
            )
            logger.info("필터 통과 %d건이 queued에 추가됨", len(passed))

        report = analyze_queued(
            store=store,
            output_dir=cfg.output_dir,
            ports=AnalysisPorts(
                generator=GeminiGenerator(client, models.generator),
                blind_extractor=GeminiBlindExtractor(client, models.blind),
                description_parser=GeminiDescriptionParser(client, models.description),
                judge=GeminiJudge(client, models.judge),
                matcher=GeminiMatcher(client, models.matcher),
            ),
            meta_fetcher=lambda vid: get_video_meta(cfg.youtube_api_key, vid),
            count=args.count,
        )
        report.discovered = discovered
        logger.info(report.summary_line())
        for vid, reason in report.failed:
            logger.warning("[%s] %s", vid, reason)
        return 0 if not report.failed or report.analyzed else 1
    finally:
        store.close()


def _cmd_publish_dev(args: argparse.Namespace) -> int:
    """dev 등록 — prod 등록은 CLI에 없다 (사람이 대시보드 버튼으로만)."""
    import json
    from pathlib import Path

    from unbake.adapters.naembii.client import NaembiiClient, publish_and_verify
    from unbake.adapters.naembii.mapper import structure_candidate
    from unbake.models import RecipeCandidate

    cfg = Config.load()
    cfg.require("dev_api_host", "dev_admin_secret")

    video_dir = cfg.output_dir / args.video_id
    candidate_path = Path(args.revision) if args.revision else video_dir / "candidate.json"
    if not candidate_path.exists():
        logger.error("candidate 산출물이 없습니다: %s", candidate_path)
        return 1
    candidate = RecipeCandidate.model_validate(
        json.loads(candidate_path.read_text(encoding="utf-8"))
    )
    meta_path = video_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None

    result = structure_candidate(candidate, meta)
    for warning in result.warnings:
        logger.warning(warning)
    if result.request is None:
        logger.error("하드 규칙 위반 — 등록 불가:")
        for error in result.errors:
            logger.error("  - %s", error)
        return 1
    if result.normalized_units or result.padded_boundaries:
        logger.info(
            "후처리: 단위 정규화 %d곳 / 경계 패딩 %d개",
            result.normalized_units,
            result.padded_boundaries,
        )

    client = NaembiiClient(cfg.dev_api_host, cfg.dev_admin_secret)
    outcome = publish_and_verify(client, result.request.model_dump(exclude_none=True))
    logger.info("결과: %s", outcome)
    return 0 if outcome.status in ("created", "duplicate") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="unbake", description="교차 검증 레시피 파이프라인")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG 로그 (LLM 호출 상세)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_eval = sub.add_parser("evaluate", help="영상 1건 추출+교차 검증 (Gemini A/B)")
    p_eval.add_argument("url", help="유튜브 URL 또는 videoId")
    p_eval.add_argument(
        "--duration-ms", type=int, default=None, help="영상 길이(ms) — 생략 시 YouTube API 조회"
    )
    p_eval.add_argument(
        "--description", default=None, help="설명란 텍스트 — 생략 시 YouTube API 조회"
    )
    p_eval.set_defaults(func=_cmd_evaluate)

    p_batch = sub.add_parser("batch", help="탐색→필터→분석·평가 배치 (검수는 대시보드에서)")
    p_batch.add_argument("--count", type=int, default=3, help="분석할 queued 영상 수 (기본 3)")
    p_batch.add_argument("--top-n", type=int, default=15, help="필터 통과 상한 (기본 15)")
    p_batch.add_argument("--searches", type=int, default=5, help="검색 트랙 호출 수 (기본 5)")
    p_batch.add_argument(
        "--skip-discover", action="store_true", help="탐색·필터 생략 — 기존 queued만 분석"
    )
    p_batch.set_defaults(func=_cmd_batch)

    p_pub = sub.add_parser("publish-dev", help="승인된 candidate를 dev 백엔드에 등록")
    p_pub.add_argument("video_id", help="output/<videoId>/ 산출물 대상")
    p_pub.add_argument(
        "--revision", default=None, help="특정 revision 파일 경로 (기본: candidate.json)"
    )
    p_pub.set_defaults(func=_cmd_publish_dev)

    args = parser.parse_args(argv)
    setup_cli_logging(verbose=args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
