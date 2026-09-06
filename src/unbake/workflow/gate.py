"""요리 도메인 게이트를 파이프라인에 꽂는 자리 — evaluate(단건)·batch(큐) 공통.

판정(통과·탈락 모두)을 output/<videoId>/domain-check.json 으로 남긴다 — 모델·프롬프트
버전·usage 포함. 탈락 영상 폴더에는 candidate.json 이 없으므로 검수 대시보드 목록에는
잡히지 않는다 (review.service 는 candidate.json 이 있는 폴더만 읽는다).
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from unbake.filtering.domain import DomainJudgePort, GateResult, check_domain

logger = logging.getLogger(__name__)

DOMAIN_CHECK_FILENAME = "domain-check.json"


def run_domain_gate(
    judge: DomainJudgePort,
    *,
    video_id: str,
    title: str,
    channel_title: str,
    duration_ms: int | None,
    description: str,
    output_dir: Path,
) -> GateResult:
    """judge 1콜 → 결정 → 산출물 기록. judge 예외는 그대로 전파한다 (조용한 통과 금지)."""
    result = check_domain(
        judge, title=title, channel_title=channel_title,
        duration_ms=duration_ms, description=description,
    )
    target = Path(output_dir) / video_id
    target.mkdir(parents=True, exist_ok=True)
    payload = {
        "videoId": video_id,
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
        **result.dump(),
    }
    (target / DOMAIN_CHECK_FILENAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    v = result.verdict
    if result.passed:
        logger.info("[%s] 도메인 게이트 통과 (확신 %.2f%s)", video_id, v.confidence,
                    f", {v.dish_name}" if v.dish_name else "")
    else:
        logger.info("[%s] 도메인 게이트 탈락 — 영상 호출 안 함: %s", video_id, result.reason)
    return result
