"""⑦ 등록 — 냄비 백엔드 클라이언트.

- ADMIN 토큰: 필요 시 발급, TTL 30분 내 재사용(25분에 선제 갱신), 401 시 재발급 1회
- 409 = duplicate (멱등 성공 취급), 400 = failed(코드 보존), 5xx/네트워크 = 지수 백오프 3회
- dev/prod 공통 — host와 secret만 다르다
"""
import time
from collections.abc import Callable
from typing import Any

import requests

from unbake.publishing import PublishResult

TOKEN_REUSE_SEC = 25 * 60          # TTL 30분 — 25분까지만 재사용
RETRYABLE_TRIES = 3                # 5xx/네트워크 재시도 횟수
BACKOFF_BASE_SEC = 1.0


# 중립 계약(unbake.publishing)의 PublishResult를 그대로 사용한다 — 재노출은 하위 호환용



class NaembiiClient:
    def __init__(self, host: str, admin_secret: str,
                 session: Any | None = None,
                 sleeper: Callable[[float], None] = time.sleep):
        self.host = host.rstrip("/")
        self._secret = admin_secret
        self._session = session or requests.Session()
        self._sleep = sleeper
        self._token: str | None = None
        self._token_at: float = 0.0

    # ---- 토큰 ----
    def _issue_token(self) -> str:
        res = self._session.post(f"{self.host}/api/v1/auth/admin",
                                 json={"secret": self._secret}, timeout=10)
        if res.status_code != 200:
            raise RuntimeError(f"ADMIN 토큰 발급 실패: HTTP {res.status_code} {_code(res)}")
        self._token = res.json()["accessToken"]
        self._token_at = time.monotonic()
        return self._token

    def _get_token(self) -> str:
        if self._token and (time.monotonic() - self._token_at) < TOKEN_REUSE_SEC:
            return self._token
        return self._issue_token()

    # ---- 재시도 래퍼 (5xx/네트워크만) ----
    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(RETRYABLE_TRIES):
            try:
                res = self._session.request(
                    method, f"{self.host}{path}",
                    headers={"Authorization": f"Bearer {self._get_token()}"},
                    timeout=15, **kwargs)
            except requests.RequestException as e:
                last_exc = e
                self._sleep(BACKOFF_BASE_SEC * (2 ** attempt))
                continue
            if res.status_code == 401:            # 토큰 만료/무효 → 재발급 후 1회 재시도
                self._issue_token()
                res = self._session.request(
                    method, f"{self.host}{path}",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=15, **kwargs)
            if res.status_code >= 500:
                self._sleep(BACKOFF_BASE_SEC * (2 ** attempt))
                continue
            return res
        if last_exc:
            raise RuntimeError(f"네트워크 실패 (재시도 {RETRYABLE_TRIES}회 소진): {last_exc}")
        raise RuntimeError(f"서버 5xx (재시도 {RETRYABLE_TRIES}회 소진)")

    # ---- API ----
    def create_recipe(self, payload: dict) -> PublishResult:
        res = self._request("POST", "/api/v1/recipes", json=payload)
        if res.status_code == 201:
            return PublishResult(status="created", recipe_id=res.json().get("id"))
        if res.status_code == 409:
            return PublishResult(status="duplicate", error_code=_code(res), message=_msg(res))
        body = _safe_json(res)
        return PublishResult(status="failed", error_code=body.get("code"),
                             message=body.get("message"),
                             field_errors=body.get("fieldErrors"))

    def get_recipe(self, recipe_id: str) -> dict | None:
        res = self._request("GET", f"/api/v1/recipes/{recipe_id}")
        return res.json() if res.status_code == 200 else None


def publish_and_verify(client: NaembiiClient, payload: dict) -> PublishResult:
    """등록 + 라운드트립 검증 (dev 등록 성공 시 GET으로 저장 결과 확인)."""
    result = client.create_recipe(payload)
    if result.status != "created":
        return result
    saved = client.get_recipe(result.recipe_id)
    if saved is None:
        return PublishResult(status="failed", error_code="ROUNDTRIP_MISSING",
                             message=f"등록 직후 GET 실패: {result.recipe_id}")
    mismatches = []
    if saved.get("dishName") != payload["dishName"]:
        mismatches.append("dishName")
    if len(saved.get("steps", [])) != len(payload["steps"]):
        mismatches.append("steps 개수")
    if len(saved.get("ingredients", [])) != len(payload["ingredients"]):
        mismatches.append("ingredients 개수")
    if mismatches:
        return PublishResult(status="failed", error_code="ROUNDTRIP_MISMATCH",
                             recipe_id=result.recipe_id,
                             message="라운드트립 불일치: " + ", ".join(mismatches))
    return result


def _safe_json(res: requests.Response) -> dict:
    try:
        return res.json()
    except Exception:
        return {}


def _code(res) -> str | None:
    return _safe_json(res).get("code")


def _msg(res) -> str | None:
    return _safe_json(res).get("message")
