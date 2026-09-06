"""Gemini 추출기 3종 — A(생성) / B(블라인드) / 설명란 파서.

B의 메서드는 영상 참조만 받는다 — blind 격벽은 시그니처가 보장한다.
"""

from pydantic import ValidationError

from unbake.adapters.gemini.client import GeminiClient
from unbake.evaluation.recovery import LlmParseError
from unbake.extraction.prompt_store import Prompt, load_prompt
from unbake.models import BlindExtraction, DescriptionFacts, LlmCallRecord, RecipeCandidate


def _record(purpose: str, model: str, prompt: Prompt, usage: dict) -> LlmCallRecord:
    return LlmCallRecord(
        call_id=f"{purpose}-1",
        purpose=purpose,
        model=model,
        prompt_version=prompt.version,
        prompt_hash=prompt.hash,
        usage=usage,
    )


class GeminiGenerator:
    """Gemini A — 영상 + 설명란 → RecipeCandidate."""

    def __init__(self, client: GeminiClient, model: str):
        self._client = client
        self._model = model
        self._prompt = load_prompt("generator")

    def extract_candidate(
        self, video_url: str, video_id: str, duration_ms: int | None, description: str
    ) -> tuple[RecipeCandidate, LlmCallRecord]:
        rendered = self._prompt.render(
            VIDEO_ID=video_id,
            DURATION_MS=duration_ms if duration_ms is not None else "알 수 없음",
            DESCRIPTION=description or "(설명란 없음)",
        )
        data, usage = self._client.generate_json(self._model, rendered, video_url=video_url)
        try:
            candidate = RecipeCandidate.model_validate(data)
        except ValidationError as exc:
            raise LlmParseError(f"RecipeCandidate 계약 위반: {exc}") from exc
        candidate.video_id = video_id  # 모델이 뭐라 했든 실제 값으로 고정
        if duration_ms is not None:
            candidate.duration_ms = duration_ms
        return candidate, _record("extract_a", self._model, self._prompt, usage)


class GeminiBlindExtractor:
    """Gemini B — 영상만 → 사실·동작. A 결과·설명란은 받을 수 없다."""

    def __init__(self, client: GeminiClient, model: str):
        self._client = client
        self._model = model
        self._prompt = load_prompt("blind_extractor")

    def extract_facts(
        self, video_url: str, duration_ms: int | None
    ) -> tuple[BlindExtraction, LlmCallRecord]:
        rendered = self._prompt.render(
            DURATION_MS=duration_ms if duration_ms is not None else "알 수 없음"
        )
        data, usage = self._client.generate_json(self._model, rendered, video_url=video_url)
        try:
            blind = BlindExtraction.model_validate(data)
        except ValidationError as exc:
            raise LlmParseError(f"BlindExtraction 계약 위반: {exc}") from exc
        return blind, _record("extract_b", self._model, self._prompt, usage)


class GeminiDescriptionParser:
    """설명란만 → 사실. 영상은 첨부하지 않는다 (저렴한 텍스트 호출)."""

    def __init__(self, client: GeminiClient, model: str):
        self._client = client
        self._model = model
        self._prompt = load_prompt("description_parser")

    def parse(self, description: str) -> tuple[DescriptionFacts, LlmCallRecord]:
        rendered = self._prompt.render(DESCRIPTION=description or "(설명란 없음)")
        data, usage = self._client.generate_json(self._model, rendered)
        try:
            facts = DescriptionFacts.model_validate(data)
        except ValidationError as exc:
            raise LlmParseError(f"DescriptionFacts 계약 위반: {exc}") from exc
        return facts, _record("parse_description", self._model, self._prompt, usage)
