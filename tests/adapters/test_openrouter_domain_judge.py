"""도메인 판정 어댑터 — 프롬프트 렌더링, JSON 계약 검증, provenance 전달."""
import pytest

from unbake.adapters.openrouter.domain_judge import LlmDomainJudge
from unbake.evaluation.recovery import LlmParseError


class FakeClient:
    """generate_json 계약만 구현 — OpenRouterClient/GeminiClient 어느 쪽 대역이든 된다."""

    def __init__(self, data):
        self.data, self.calls = data, []

    def generate_json(self, model, prompt, temperature=0.0):
        self.calls.append((model, prompt, temperature))
        return self.data, {"prompt_tokens": 3}


def test_판정을_DomainVerdict로_옮기고_provenance를_붙인다():
    client = FakeClient({"isCooking": True, "confidence": 0.85, "dishName": "김치찌개",
                         "reason": "제목·설명란에 재료와 조리 과정"})
    verdict = LlmDomainJudge(client, "some/model").judge("제목: 김치찌개")

    assert verdict.is_cooking is True and verdict.confidence == 0.85
    assert verdict.dish_name == "김치찌개"
    assert verdict.model == "some/model" and verdict.prompt_version and verdict.prompt_hash
    assert verdict.usage == {"prompt_tokens": 3}
    model, prompt, temperature = client.calls[0]
    assert "제목: 김치찌개" in prompt and "{{VIDEO}}" not in prompt and temperature == 0.0


@pytest.mark.parametrize("confidence", [0, 0.5, 1])
def test_유효한_confidence_경계값과_dishName_null_허용(confidence):
    verdict = LlmDomainJudge(FakeClient({"isCooking": False, "confidence": confidence,
                                       "dishName": None}),
                             "m").judge("x")
    assert verdict.confidence == confidence and verdict.dish_name is None


@pytest.mark.parametrize("bad", [
    ["not", "an", "object"],
    {"confidence": 0.9},                 # isCooking 없음
    {"isCooking": "yes"},                # boolean 아님
    {"isCooking": True, "confidence": "high"},
    {"isCooking": True},
    *({"isCooking": True, "confidence": value} for value in [
        None, True, False, "NaN", "0.9", float("nan"), float("inf"), float("-inf"),
        -0.1, 3, [], {},
    ]),
])
def test_계약_위반은_LlmParseError(bad):
    with pytest.raises(LlmParseError):
        LlmDomainJudge(FakeClient(bad), "m").judge("x")
