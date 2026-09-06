"""② 필터의 LLM 판별 — filtering.filter.run_filter의 `judge` 계약 구현.

후보 목록 텍스트 블록을 받아 {"verdicts": [...]}를 돌려준다 (배치 1콜).
"""

from unbake.adapters.gemini.client import GeminiClient
from unbake.evaluation.recovery import LlmParseError
from unbake.extraction.prompt_store import load_prompt


class GeminiFilterJudge:
    def __init__(self, client: GeminiClient, model: str):
        self._client = client
        self._model = model
        self._prompt = load_prompt("filter_verdict")

    def __call__(self, candidates_block: str) -> dict:
        rendered = self._prompt.render(CANDIDATES=candidates_block)
        data, _usage = self._client.generate_json(self._model, rendered)
        if not isinstance(data, dict) or not isinstance(data.get("verdicts"), list):
            raise LlmParseError("필터 판별 응답에 verdicts 배열이 없다")
        return data
