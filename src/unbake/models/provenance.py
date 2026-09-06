"""Provenance — 어떤 모델·프롬프트·시도가 이 산출물을 만들었는지의 기록.

사람 수정 로그와 quality event를 조인하는 기반이므로 M0에서 고정한 계약이다.
모델 ID는 `latest` 별칭 없이 정확히 고정해 기록한다.
"""

from unbake.models.base import ApiModel


class LlmCallRecord(ApiModel):
    """LLM 호출 1회의 기록 — 재시도·부분 재호출 포함 전부 남긴다."""

    call_id: str
    purpose: str  # extract_a | extract_b | parse_description | judge_<source> | match_steps
    model: str  # 정확한 모델 ID
    prompt_version: str
    prompt_hash: str
    attempt: int = 1
    repair_of_call_id: str | None = None  # 부분 재호출이면 원 호출 ID
    requested_ids: list[str] | None = None  # 부분 재호출에서 요청한 claim/subStep ID
    status: str = "succeeded"  # succeeded | parse_failed | schema_invalid | input_too_large
    usage: dict | None = None  # 토큰 사용량 (provider 원본 그대로)


class RunManifest(ApiModel):
    """평가 실행 1회의 manifest."""

    evaluation_run_id: str
    schema_version: str
    input_hash: str  # 입력 snapshot(candidate + facts + 프롬프트 버전)의 해시
    created_at: str  # ISO8601
    calls: list[LlmCallRecord] = []
