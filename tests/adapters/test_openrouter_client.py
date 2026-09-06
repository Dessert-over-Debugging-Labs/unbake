"""OpenRouter 클라이언트 — 요청 형태, 일시 오류 재시도, 파싱 실패, 키 비노출."""
import json

import pytest
import requests

from unbake.adapters.openrouter import client as C
from unbake.evaluation.recovery import InputTooLargeError, LlmParseError


class FakeResponse:
    def __init__(self, status: int, payload=None, text: str = ""):
        self.status_code = status
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")

    def json(self):
        return self._payload


def _chat(content: str, usage=None):
    return {"choices": [{"message": {"content": content}}],
            "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5}}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(C.time, "sleep", lambda _s: None)


def test_요청은_json_object_모드_bearer_키로_나간다(monkeypatch):
    seen = {}

    def fake_post(url, *, headers, json, timeout):
        seen.update(url=url, headers=headers, body=json, timeout=timeout)
        return FakeResponse(200, _chat('{"isCooking": true}'))

    monkeypatch.setattr(C.requests, "post", fake_post)
    data, usage = C.OpenRouterClient("sk-test").generate_json("some/model", "안녕")

    assert data == {"isCooking": True}
    assert usage["prompt_tokens"] == 10 and "elapsedSec" in usage
    assert seen["headers"]["Authorization"] == "Bearer sk-test"
    assert seen["body"]["model"] == "some/model"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["messages"] == [{"role": "user", "content": "안녕"}]


def test_코드펜스로_감싼_JSON도_파싱한다(monkeypatch):
    monkeypatch.setattr(C.requests, "post",
                        lambda *a, **k: FakeResponse(200, _chat('```json\n{"a": 1}\n```')))
    data, _ = C.OpenRouterClient("k").generate_json("m", "p")
    assert data == {"a": 1}


def test_일시_오류는_재시도하고_소진되면_OpenRouterError(monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        return FakeResponse(503, text="overloaded")

    monkeypatch.setattr(C.requests, "post", flaky)
    with pytest.raises(C.OpenRouterError, match="재시도"):
        C.OpenRouterClient("k").generate_json("m", "p")
    assert calls["n"] == C._RETRY_MAX + 1


def test_전송_예외도_재시도_대상(monkeypatch):
    calls = {"n": 0}

    def then_ok(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.ConnectionError("reset")
        return FakeResponse(200, _chat('{"ok": true}'))

    monkeypatch.setattr(C.requests, "post", then_ok)
    data, _ = C.OpenRouterClient("k").generate_json("m", "p")
    assert data == {"ok": True} and calls["n"] == 2


def test_비일시_오류는_즉시_실패_그리고_키는_메시지에_없다(monkeypatch):
    monkeypatch.setattr(C.requests, "post",
                        lambda *a, **k: FakeResponse(401, text="invalid api key"))
    with pytest.raises(C.OpenRouterError) as exc:
        C.OpenRouterClient("sk-secret-value").generate_json("m", "p")
    assert "401" in str(exc.value) and "sk-secret-value" not in str(exc.value)


def test_context_초과는_InputTooLargeError(monkeypatch):
    monkeypatch.setattr(C.requests, "post",
                        lambda *a, **k: FakeResponse(400, text="maximum context length exceeded"))
    with pytest.raises(InputTooLargeError):
        C.OpenRouterClient("k").generate_json("m", "p")


def test_응답이_JSON이_아니면_LlmParseError(monkeypatch):
    monkeypatch.setattr(C.requests, "post",
                        lambda *a, **k: FakeResponse(200, _chat("죄송하지만 판단할 수 없습니다")))
    with pytest.raises(LlmParseError):
        C.OpenRouterClient("k").generate_json("m", "p")
