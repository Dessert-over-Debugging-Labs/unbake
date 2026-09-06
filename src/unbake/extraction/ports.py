"""추출 port — 시그니처가 blind 격벽을 구조적으로 보장한다.

BlindExtractorPort는 영상 참조만 받는다. A의 결과도, 설명란도 넘길 방법이 없다.
"""

from typing import Protocol

from unbake.models import BlindExtraction, DescriptionFacts, LlmCallRecord, RecipeCandidate


class GeneratorPort(Protocol):
    """Gemini A — 영상 + 설명란 → RecipeCandidate (얇은 IR)."""

    def extract_candidate(
        self, video_url: str, video_id: str, duration_ms: int | None, description: str
    ) -> tuple[RecipeCandidate, LlmCallRecord]: ...


class BlindExtractorPort(Protocol):
    """Gemini B — 영상만 → 사실·동작. A 결과·설명란은 받을 수 없다."""

    def extract_facts(
        self, video_url: str, duration_ms: int | None
    ) -> tuple[BlindExtraction, LlmCallRecord]: ...


class DescriptionParserPort(Protocol):
    """설명란만 → 사실."""

    def parse(self, description: str) -> tuple[DescriptionFacts, LlmCallRecord]: ...
