"""요리 도메인 게이트 — 영상 링크를 모델에 넣기 전에 "요리 영상인가"를 싼 텍스트 판정으로 거른다.

영상 호출(A·B 2회)은 비싸다. 이 게이트는 제목·채널·길이·설명란만 보고 그 앞을 막는다.
판정은 주입된 judge(어댑터)가 하고, 통과/탈락 결정·사유 문자열·임계값은 여기(결정적 코드)가
소유한다 — 임계값이 프롬프트가 아니라 코드에 있어야 측정하고 조정할 수 있다.

실패 정책: 판정 자체가 실패(네트워크·파싱)하면 통과시키지 않고 예외를 그대로 올린다.
조용히 통과시키면 "게이트가 있다"는 가정이 깨진다.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

# isCooking=true 여도 이 밑이면 탈락 — 확신 없는 통과는 비싼 영상 호출 낭비
MIN_CONFIDENCE = 0.5
# 설명란은 앞부분만 — 재료·요리명은 보통 앞에 있고, 뒤는 링크·해시태그다
DESCRIPTION_MAX_CHARS = 1500

OFF_DOMAIN = "off_domain"  # 탈락 사유 접두
DOMAIN_CHECK_FILENAME = "domain-check.json"


@dataclass
class DomainVerdict:
    """judge가 돌려주는 판정 — provenance(모델·프롬프트 버전·usage)까지 함께."""

    is_cooking: bool
    confidence: float  # 이 영상이 요리 영상일 확률 0.0~1.0
    reason: str = ""
    dish_name: str | None = None
    model: str = ""
    prompt_version: str = ""
    prompt_hash: str = ""
    usage: dict | None = None

    def dump(self) -> dict:
        return {
            "isCooking": self.is_cooking,
            "confidence": self.confidence,
            "reason": self.reason,
            "dishName": self.dish_name,
            "model": self.model,
            "promptVersion": self.prompt_version,
            "promptHash": self.prompt_hash,
            "usage": self.usage,
        }


class DomainJudgePort(Protocol):
    """메타 텍스트 블록(video_block 형식) → DomainVerdict. 프롬프트·JSON 검증은 어댑터 책임."""

    def judge(self, video_block: str) -> DomainVerdict: ...


@dataclass
class GateResult:
    passed: bool
    reason: str  # 탈락이면 "off_domain: ...", 통과면 ""
    verdict: DomainVerdict

    def dump(self) -> dict:
        return {"passed": self.passed, "reason": self.reason, "verdict": self.verdict.dump()}


def video_block(*, title: str, channel_title: str, duration_ms: int | None,
                description: str) -> str:
    """judge에 넘길 메타 블록 — 프롬프트 템플릿의 {{VIDEO}} 자리에 그대로 들어간다."""
    desc = (description or "").strip()
    if len(desc) > DESCRIPTION_MAX_CHARS:
        desc = desc[:DESCRIPTION_MAX_CHARS] + " …(이하 생략)"
    length = f"{duration_ms // 1000}s" if duration_ms else "(모름)"
    return "\n".join([
        f"제목: {title or '(없음)'}",
        f"채널: {channel_title or '(없음)'}",
        f"길이: {length}",
        "설명란:",
        desc or "(비어 있음)",
    ])


def decide(verdict: DomainVerdict) -> GateResult:
    """판정 → 통과/탈락. 임계값은 코드가 소유한다."""
    if not verdict.is_cooking:
        return GateResult(False, f"{OFF_DOMAIN}: {verdict.reason or '요리 영상 아님'}", verdict)
    if verdict.confidence < MIN_CONFIDENCE:
        return GateResult(
            False,
            f"{OFF_DOMAIN}: 확신 부족 {verdict.confidence:.2f} < {MIN_CONFIDENCE}"
            + (f" ({verdict.reason})" if verdict.reason else ""),
            verdict,
        )
    return GateResult(True, "", verdict)


def check_domain(judge: DomainJudgePort, *, title: str, channel_title: str,
                 duration_ms: int | None, description: str) -> GateResult:
    """메타 → judge 1콜 → 결정. judge 예외는 그대로 전파한다 (조용한 통과 금지)."""
    verdict = judge.judge(video_block(
        title=title, channel_title=channel_title, duration_ms=duration_ms,
        description=description,
    ))
    return decide(verdict)


def run_domain_gate(
    judge: DomainJudgePort,
    *,
    video_id: str,
    title: str,
    channel_title: str,
    duration_ms: int | None,
    description: str,
    output_dir: Path | None = None,
) -> GateResult:
    """check_domain + 산출물 기록.

    output_dir 이 있으면 <output_dir>/<videoId>/domain-check.json 을 쓴다.
    통과·탈락 모두 기록한다 — 모델·프롬프트 버전·usage 가 provenance 다.
    """
    result = check_domain(
        judge, title=title, channel_title=channel_title,
        duration_ms=duration_ms, description=description,
    )
    if output_dir is not None:
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
