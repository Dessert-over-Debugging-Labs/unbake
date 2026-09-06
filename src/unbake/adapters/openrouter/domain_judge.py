"""요리 도메인 게이트의 LLM 판정 — gate.DomainJudgePort 구현.

영상 메타(제목·채널·길이·설명란)만 보고 "요리 영상인가"를 판정한다. 영상은 보지
않는다 — 그래서 싼 텍스트 모델이면 충분하고, `generate_json`을 가진 클라이언트라면
OpenRouterClient든 GeminiClient든 그대로 꽂힌다 (DOMAIN_CHECK=gemini).

프롬프트 구성·JSON 계약 검증은 여기(어댑터) 책임이고, 통과/탈락 결정은
unbake.gate(결정적 코드)가 한다.
"""

from typing import Protocol

from unbake.evaluation.recovery import LlmParseError
from unbake.extraction.prompt_store import load_prompt
from unbake.gate import DomainVerdict


class JsonClient(Protocol):
    def generate_json(
        self, model: str, prompt: str, temperature: float = 0.0
    ) -> tuple[dict | list, dict]: ...


class LlmDomainJudge:
    purpose = "domain_check"

    def __init__(self, client: JsonClient, model: str):
        self._client = client
        self._model = model
        self._prompt = load_prompt("domain_check")

    def judge(self, video_block: str) -> DomainVerdict:
        rendered = self._prompt.render(VIDEO=video_block)
        data, usage = self._client.generate_json(self._model, rendered)
        if not isinstance(data, dict) or not isinstance(data.get("isCooking"), bool):
            raise LlmParseError("도메인 판정 응답에 isCooking(boolean)이 없다")
        try:
            confidence = float(data.get("confidence") or 0.0)
        except (TypeError, ValueError) as exc:
            raise LlmParseError(f"confidence가 숫자가 아니다: {data.get('confidence')!r}") from exc
        dish = data.get("dishName")
        return DomainVerdict(
            is_cooking=data["isCooking"],
            confidence=max(0.0, min(1.0, confidence)),
            reason=str(data.get("reason") or ""),
            dish_name=str(dish) if dish else None,
            model=self._model,
            prompt_version=self._prompt.version,
            prompt_hash=self._prompt.hash,
            usage=usage,
        )
