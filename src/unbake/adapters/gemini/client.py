"""Gemini API 클라이언트 — YouTube URL을 다운로드 없이 직접 첨부한다.

실측 근거(과거 실측): 9분 영상 1패스 약 6만 토큰/80초,
재료 16/16 일치, 구간 시작점 평균 오차 2.0초. 키는 GEMINI_API_KEY env로만 받는다.
"""

import json
import logging
import time

import requests

from unbake.evaluation.recovery import InputTooLargeError, LlmParseError

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

logger = logging.getLogger(__name__)


class GeminiError(Exception):
    """전송·API 오류 (재시도 대상은 호출자가 판단)."""


# 일시 오류(503 과부하·rate-limit 429) 재시도 — 하드 쿼터(429 limit: 0)는 재시도 안 함
_RETRY_MAX = 3
_RETRY_BASE_SEC = 4.0


class GeminiClient:
    def __init__(self, api_key: str, timeout_sec: int = 900):
        self._api_key = api_key
        self._timeout = timeout_sec

    def _post_with_retry(self, model: str, body: dict) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(_RETRY_MAX + 1):
            if attempt:
                delay = _RETRY_BASE_SEC * (2 ** (attempt - 1))
                logger.debug(
                    "gemini %s 재시도 %d/%d (%.0fs 대기)", model, attempt, _RETRY_MAX, delay
                )
                time.sleep(delay)
            try:
                res = requests.post(
                    _ENDPOINT.format(model=model),
                    params={"key": self._api_key},
                    json=body,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                continue
            transient = res.status_code == 503 or (
                res.status_code == 429 and "limit: 0" not in res.text
            )
            if not transient:
                return res
            last_error = GeminiError(f"HTTP {res.status_code}: {res.text[:300]}")
        raise GeminiError(f"재시도 {_RETRY_MAX}회 소진: {last_error}") from last_error

    def generate_json(
        self,
        model: str,
        prompt: str,
        video_url: str | None = None,
        temperature: float = 0.0,
    ) -> tuple[dict | list, dict]:
        """JSON 모드로 호출한다. (파싱 결과, usage) 반환.

        video_url이 있으면 file_data로 첨부한다 — 다운로드하지 않는다.
        """
        parts: list[dict] = []
        if video_url:
            parts.append({"file_data": {"file_uri": video_url}})
        parts.append({"text": prompt})
        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": temperature,
            },
        }
        started = time.time()
        res = self._post_with_retry(model, body)

        if res.status_code == 400 and "token" in res.text.lower():
            # context 한계 초과 — 재시도해도 소용없다 (INPUT_TOO_LARGE)
            raise InputTooLargeError(res.text[:500])
        if res.status_code != 200:
            raise GeminiError(f"HTTP {res.status_code}: {res.text[:500]}")

        payload = res.json()
        usage = payload.get("usageMetadata", {})
        usage["elapsedSec"] = round(time.time() - started, 1)
        logger.debug(
            "gemini %s: %ss, in=%s out=%s",
            model,
            usage["elapsedSec"],
            usage.get("promptTokenCount"),
            usage.get("candidatesTokenCount"),
        )
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text), usage
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LlmParseError(f"응답 파싱 실패: {exc}") from exc
