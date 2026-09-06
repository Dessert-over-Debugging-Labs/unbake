"""요리 도메인 게이트 — 영상 링크를 모델에 넣기 전에 "요리 영상인가"를 싼 텍스트 판정으로 거른다.

② 필터의 isRecipe 판별은 배치 탐색 경로에만 있다. `unbake evaluate <url>`처럼 사람이
직접 넣은 링크나 과거에 queued된 후보는 그 판별 없이 비싼 영상 호출(A·B 2회)로 간다.
이 게이트가 모든 경로의 영상 호출 바로 앞을 막는다.

판정은 주입된 judge(어댑터)가 하고, 통과/탈락 결정·사유 문자열·임계값은 여기(결정적
코드)가 소유한다 — 임계값이 프롬프트가 아니라 코드에 있어야 측정하고 조정할 수 있다.

실패 정책: 판정 자체가 실패(네트워크·파싱)하면 통과시키지 않고 예외를 그대로 올린다.
호출자가 실패로 기록한다. 조용히 통과시키면 "게이트가 있다"는 가정이 깨진다.
"""
from dataclasses import dataclass
from typing import Protocol

# isCooking=true 여도 이 밑이면 탈락 — 확신 없는 통과는 비싼 영상 호출 낭비
MIN_CONFIDENCE = 0.5
# 설명란은 앞부분만 — 재료·요리명은 보통 앞에 있고, 뒤는 링크·해시태그다
DESCRIPTION_MAX_CHARS = 1500

OFF_DOMAIN = "off_domain"  # 탈락 사유 접두 (② 필터의 consent_required / llm_rejected 와 같은 꼴)


@dataclass
class DomainVerdict:
    """judge가 돌려주는 판정 — provenance(모델·프롬프트 버전·usage)까지 함께."""

    is_cooking: bool
    confidence: float
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
    reason: str  # 탈락이면 "off_domain: ..." (이력 reason 컬럼에 그대로), 통과면 ""
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
