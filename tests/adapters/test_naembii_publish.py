import pytest
import requests

from unbake.adapters.naembii.client import NaembiiClient, publish_and_verify


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeSession:
    """스크립트된 응답을 순서대로 반환. 요청 기록 보관."""

    def __init__(self):
        self.token_responses = [FakeResponse(200, {"accessToken": "tok-1"})]
        self.responses = []
        self.calls = []          # (method, url)
        self.token_calls = 0

    def post(self, url, **kwargs):          # 토큰 발급 전용
        self.token_calls += 1
        self.calls.append(("POST", url))
        if self.token_responses:
            return self.token_responses.pop(0)
        return FakeResponse(200, {"accessToken": f"tok-{self.token_calls}"})

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make_client(session):
    return NaembiiClient("https://api-dev.example.com", "secret",
                         session=session, sleeper=lambda s: None)


PAYLOAD = {"dishName": "순두부찌개", "steps": [1, 2, 3], "ingredients": [1, 2]}


def test_created():
    s = FakeSession()
    s.responses = [FakeResponse(201, {"id": "r-1"})]
    res = make_client(s).create_recipe(PAYLOAD)
    assert res.status == "created" and res.recipe_id == "r-1"
    assert s.token_calls == 1


def test_duplicate_409():
    s = FakeSession()
    s.responses = [FakeResponse(409, {"code": "SOURCE_VIDEO_ALREADY_REGISTERED", "message": "dup"})]
    res = make_client(s).create_recipe(PAYLOAD)
    assert res.status == "duplicate"
    assert res.error_code == "SOURCE_VIDEO_ALREADY_REGISTERED"


def test_400_failed_with_field_errors():
    s = FakeSession()
    s.responses = [FakeResponse(400, {"code": "INVALID_INPUT", "message": "bad",
                                      "fieldErrors": [{"field": "summary"}]})]
    res = make_client(s).create_recipe(PAYLOAD)
    assert res.status == "failed" and res.error_code == "INVALID_INPUT"
    assert res.field_errors == [{"field": "summary"}]


def test_401_reissues_token_once():
    s = FakeSession()
    s.responses = [FakeResponse(401, {"code": "AUTH_ACCESS_TOKEN_INVALID"}),
                   FakeResponse(201, {"id": "r-2"})]
    res = make_client(s).create_recipe(PAYLOAD)
    assert res.status == "created"
    assert s.token_calls == 2  # 최초 발급 + 401 재발급


def test_5xx_backoff_then_success():
    s = FakeSession()
    s.responses = [FakeResponse(500), FakeResponse(503), FakeResponse(201, {"id": "r-3"})]
    res = make_client(s).create_recipe(PAYLOAD)
    assert res.status == "created" and res.recipe_id == "r-3"


def test_5xx_exhausted_raises():
    s = FakeSession()
    s.responses = [FakeResponse(500)] * 3
    with pytest.raises(RuntimeError, match="5xx"):
        make_client(s).create_recipe(PAYLOAD)


def test_network_error_retry_then_raise():
    s = FakeSession()
    s.responses = [requests.ConnectionError("boom")] * 3
    with pytest.raises(RuntimeError, match="네트워크"):
        make_client(s).create_recipe(PAYLOAD)


def test_roundtrip_verify_ok():
    s = FakeSession()
    s.responses = [FakeResponse(201, {"id": "r-9"}),
                   FakeResponse(200, {"dishName": "순두부찌개",
                                      "steps": [1, 2, 3], "ingredients": [1, 2]})]
    res = publish_and_verify(make_client(s), PAYLOAD)
    assert res.status == "created" and res.recipe_id == "r-9"


def test_roundtrip_mismatch_detected():
    s = FakeSession()
    s.responses = [FakeResponse(201, {"id": "r-9"}),
                   FakeResponse(200, {"dishName": "다른요리", "steps": [1], "ingredients": []})]
    res = publish_and_verify(make_client(s), PAYLOAD)
    assert res.status == "failed" and res.error_code == "ROUNDTRIP_MISMATCH"
