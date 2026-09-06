"""Quality events — 파이프라인의 모든 의미 있는 결정을 immutable 파일로 남긴다.

`output/quality-events/<createdAt>-<eventId>.json` — 파일 하나가 이벤트 하나.
한 JSONL을 여러 작업자가 append하면 동기화가 충돌하고, 로컬 DB만 쓰면 팀 데이터가
안 합쳐진다 — 그래서 이벤트당 파일이다 (과거 설계 기록).

이 로그는 Risk Phase 1(Shadow)의 원료다: 평가가 무엇을 놓쳤고 사람이 무엇을
고쳤는지를 나중에 조인하려면, 지금부터 전부 기록되어 있어야 한다.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

EVENT_SCHEMA_VERSION = "1.0.0"

# eventType — 표기 규칙: 영어 (한글 핵심 구절)
EVENT_TYPES = {
    "ANALYZED",  # 분석·평가 완료 (agent)
    "REVISED",  # 사람 수정 → 새 revision
    "APPROVED",  # 승인
    "REJECTED",  # 반려
    "PUBLISHED",  # 등록 (dev/prod — data.env로 구분)
    "ESCALATED",  # 상위 모델 재분석 (M4 이후)
}

EVENTS_DIRNAME = "quality-events"


def record_event(
    output_dir: Path,
    *,
    video_id: str,
    event_type: str,
    data: dict | None = None,
    actor: str = "human",
) -> str:
    """이벤트 파일 1개를 쓴다. 반환: eventId. 기존 파일은 절대 수정하지 않는다."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"알 수 없는 eventType: {event_type}")
    event_id = uuid.uuid4().hex[:12]
    created_at = datetime.now(UTC).isoformat(timespec="seconds")
    payload = {
        "schemaVersion": EVENT_SCHEMA_VERSION,
        "eventId": event_id,
        "videoId": video_id,
        "eventType": event_type,
        "actor": actor,  # human | agent
        "createdAt": created_at,
        "data": data or {},
    }
    target_dir = Path(output_dir) / EVENTS_DIRNAME
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = created_at.replace(":", "").replace("+0000", "Z").replace("+00:00", "Z")
    path = target_dir / f"{stamp}-{event_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.debug("quality event %s %s (%s)", event_type, event_id, video_id)
    return event_id


def list_events(output_dir: Path, video_id: str | None = None) -> list[dict]:
    """이벤트를 시간순으로 읽는다 (파일명이 createdAt으로 시작하므로 정렬 = 시간순)."""
    target_dir = Path(output_dir) / EVENTS_DIRNAME
    if not target_dir.exists():
        return []
    events = []
    for path in sorted(target_dir.glob("*.json")):
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("깨진 이벤트 파일 건너뜀: %s", path.name)
            continue
        if video_id is None or event.get("videoId") == video_id:
            events.append(event)
    return events
