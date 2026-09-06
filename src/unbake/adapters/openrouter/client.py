"""OpenRouter 클라이언트 — OpenAI 호환 chat/completions, 텍스트 전용.

요리 도메인 게이트처럼 영상이 필요 없는 저렴한 판정에 쓴다. 영상 첨부는 지원하지
않는다 — 영상 입력은 adapters/gemini 몫이다. 키는 OPENROUTER_API_KEY env로만 받고
로그·예외 메시지에 절대 싣지 않는다.

GeminiClient와 같은 `generate_json(model, prompt) -> (parsed, usage)` 모양을 지키므로
텍스트 전용 판정 어댑터는 두 클라이언트를 구분 없이 꽂을 수 있다.
"""

import json
import logging
import re
import time

import requests

from unbake.evaluation.recovery import InputTooLargeError, LlmParseError

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

logger = logging.getLogger(__name__)


class OpenRouterError(Exception):
    """전송·API 오류 (재시도 대상은 호출자가 판단)."""


# 일시 오류(429 rate-limit · 5xx 게이트웨이) 재시도
_RETRY_MAX = 3
_RETRY_BASE_SEC = 2.0
_TRANSIENT = {429, 500, 502, 503, 504}
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _parse_json_text(text: str) -> dict | list:
    """json_object 모드여도 일부 모델은 ``` 펜스를 두른다 — 벗기고 파싱한다."""
    stripped = text.strip()
    fenced = _FENCE_RE.match(stripped)
    if fenced:
        stripped = fenced.group(1)
    return json.loads(stripped)


class OpenRouterClient:
    def __init__(self, api_key: str, timeout_sec: int = 120, app_title: str = "unbake"):
        self._api_key = api_key
        self._timeout = timeout_sec
        self._app_title = app_title  # OpenRouter 대시보드의 앱 이름 표시용 (선택 헤더)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Title": self._app_title,
        }

    def _post_with_retry(self, body: dict) -> requests.Response:
        last_error: Exception | None = None
        model = body.get("model", "?")
        for attempt in range(_RETRY_MAX + 1):
            if attempt:
                delay = _RETRY_BASE_SEC * (2 ** (attempt - 1))
                logger.debug(
                    "openrouter %s 재시도 %d/%d (%.0fs 대기)", model, attempt, _RETRY_MAX, delay
                )
                time.sleep(delay)
            try:
                res = requests.post(
                    _ENDPOINT, headers=self._headers(), json=body, timeout=self._timeout
                )
            except requests.RequestException as exc:
                last_error = exc
                continue
            if res.status_code not in _TRANSIENT:
                return res
            last_error = OpenRouterError(f"HTTP {res.status_code}: {res.text[:300]}")
        raise OpenRouterError(f"재시도 {_RETRY_MAX}회 소진: {last_error}") from last_error

    def generate_json(
        self, model: str, prompt: str, temperature: float = 0.0
    ) -> tuple[dict | list, dict]:
        """JSON 모드로 1회 호출한다. (파싱 결과, usage) 반환."""
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        started = time.time()
        res = self._post_with_retry(body)

        if res.status_code == 400 and "context" in res.text.lower():
            raise InputTooLargeError(res.text[:500])
        if res.status_code != 200:
            raise OpenRouterError(f"HTTP {res.status_code}: {res.text[:500]}")

        payload = res.json()
        usage = dict(payload.get("usage") or {})
        usage["elapsedSec"] = round(time.time() - started, 1)
        logger.debug(
            "openrouter %s: %ss, in=%s out=%s",
            model, usage["elapsedSec"], usage.get("prompt_tokens"), usage.get("completion_tokens"),
        )
        try:
            text = payload["choices"][0]["message"]["content"]
            return _parse_json_text(text), usage
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LlmParseError(f"응답 파싱 실패: {exc}") from exc
