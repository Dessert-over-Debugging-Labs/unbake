"""CLI — `unbake <youtube-url>` 로 영상 1건을 추출하고 교차 검증한다.

라이브러리로 쓰려면 `from unbake import make_recipe`. 이 파일은 그 얇은 껍데기다.
"""

import argparse
import logging
import sys

from unbake import __version__
from unbake.api import OffDomainError, make_recipe
from unbake.config import Config
from unbake.log import setup_cli_logging

logger = logging.getLogger(__name__)


def _report(artifacts) -> None:
    ev = artifacts.evaluation
    s = ev.summary
    logger.info(
        "claim %d건 — 모순 %d / 충돌 %d / 근거없음 %d",
        len(ev.claim_evaluations), s.contradiction_count,
        s.source_conflict_count, s.unknown_claim_count,
    )
    logger.info(
        "대단계 %d개 — 일치 %d / 일부 %d / 불일치 %d / 순서충돌 %d",
        len(ev.step_rollups), s.matched_step_count, s.partial_step_count,
        s.unmatched_step_count, s.order_conflict_count,
    )
    logger.info(
        "구간 — 의심 %d / 미검증 %d / 중앙값 tIoU %s",
        s.suspect_segment_count, s.unverified_segment_count, s.median_temporal_iou,
    )
    if s.omission_count:
        logger.info("누락 후보 %d건 (기록만 — 자동 탈락 아님)", s.omission_count)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="unbake",
        description="유튜브 요리 영상 → 검증된 구조화 레시피 (재료·분량·단계·타임스탬프)",
    )
    parser.add_argument("url", help="유튜브 URL 또는 videoId")
    parser.add_argument("-o", "--output", default=None,
                        help="산출물 폴더 (기본: ./output) — <output>/<videoId>/ 에 저장")
    parser.add_argument("--description", default=None,
                        help="설명란 텍스트 — 생략 시 YouTube API 조회")
    parser.add_argument("--duration-ms", type=int, default=None,
                        help="영상 길이(ms) — 생략 시 YouTube API 조회")
    parser.add_argument("--skip-domain-check", action="store_true",
                        help="요리 도메인 게이트 생략 — 영상을 바로 분석")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG 로그 (LLM 호출 상세)")
    parser.add_argument("--version", action="version", version=f"unbake {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_cli_logging(verbose=args.verbose)
    cfg = Config.load()
    if args.skip_domain_check:
        logger.info("요리 도메인 게이트: 꺼짐 (--skip-domain-check)")
    elif cfg.domain_check == "off":
        logger.info("요리 도메인 게이트: 꺼짐 (DOMAIN_CHECK=off 또는 OPENROUTER_API_KEY 없음)")
    else:
        logger.info("요리 도메인 게이트: %s / %s", cfg.domain_check, cfg.models.domain)
    try:
        artifacts = make_recipe(
            args.url,
            description=args.description,
            duration_ms=args.duration_ms,
            config=cfg,
            check_domain=False if args.skip_domain_check else None,
            output_dir=args.output,
        )
    except OffDomainError as exc:
        logger.error("요리 영상이 아니라고 판정되어 분석하지 않습니다: %s "
                     "(강제하려면 --skip-domain-check)", exc.gate.reason)
        return 2
    except (ValueError, RuntimeError) as exc:
        logger.error("%s", exc)
        return 1
    _report(artifacts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
