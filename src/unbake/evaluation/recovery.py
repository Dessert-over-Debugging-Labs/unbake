"""LLM 출력 검증·복구 상태기계 (M0/M1 고정 계약 — docs/architecture.md).

| 응답 상태                                   | 처리 |
|--------------------------------------------|------|
| 파싱 실패 · 유령 ID · 중복 ID               | 전체 재시도 (부분 병합 금지) |
| 유효 + 일부 ID 누락만                       | 누락분만 부분 재호출 (요청 ID 전수성 검사) |
| context 한계 초과                           | INPUT_TOO_LARGE 명시적 실패 (재시도 없음) |

부분 재호출이 안전한 근거: 판정 의미론은 항목별 독립(입력 = 항목 + source facts뿐).
모든 시도를 LlmCallRecord로 남기고, 부분 재호출에는 repair_of_call_id를 기록한다.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from unbake.models import LlmCallRecord

T = TypeVar("T")


class LlmParseError(Exception):
    """응답을 계약 스키마로 파싱하지 못했다."""


class InputTooLargeError(Exception):
    """입력이 모델 context 한계를 넘었다 — 재시도해도 소용없다."""


class RecoveryExhausted(Exception):
    """재시도 예산을 소진했다. records에 전체 시도 이력이 담긴다."""

    def __init__(self, message: str, records: list[LlmCallRecord]):
        super().__init__(message)
        self.records = records


@dataclass
class PortResponse(Generic[T]):
    """port 호출 1회의 응답 — provenance 필드는 adapter가 채운다."""

    items: list[T]
    model: str = ""
    prompt_version: str = ""
    prompt_hash: str = ""
    usage: dict | None = None


@dataclass
class _Classification:
    ok: bool = True
    missing: list[str] = field(default_factory=list)
    ghosts: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)

    @property
    def structural(self) -> bool:
        return bool(self.ghosts or self.duplicates)


def _classify(expected_ids: list[str], returned_ids: list[str]) -> _Classification:
    expected = set(expected_ids)
    seen: set[str] = set()
    cls = _Classification()
    for rid in returned_ids:
        if rid not in expected:
            cls.ghosts.append(rid)
        elif rid in seen:
            cls.duplicates.append(rid)
        seen.add(rid)
    cls.missing = [eid for eid in expected_ids if eid not in seen]
    cls.ok = not (cls.structural or cls.missing)
    return cls


def run_batch_with_recovery(
    purpose: str,
    expected_ids: list[str],
    call: Callable[[list[str] | None], PortResponse[T]],
    key_fn: Callable[[T], str],
    max_structural_retries: int = 2,
) -> tuple[list[T], list[LlmCallRecord]]:
    """expected_ids 전부가 정확히 1회씩 판정될 때까지 호출·검증·복구한다.

    call(None)은 전체 호출, call(ids)는 해당 ID만 부분 재호출.
    반환 항목은 expected_ids 순서로 정렬된다.
    """
    if not expected_ids:
        return [], []

    records: list[LlmCallRecord] = []
    accepted: dict[str, T] = {}
    call_seq = 0
    structural_budget = max_structural_retries

    def attempt(
        requested: list[str] | None, repair_of: str | None
    ) -> tuple[str, PortResponse[T] | None]:
        nonlocal call_seq
        call_seq += 1
        call_id = f"{purpose}-{call_seq}"
        record = LlmCallRecord(
            call_id=call_id,
            purpose=purpose,
            model="",
            prompt_version="",
            prompt_hash="",
            attempt=call_seq,
            repair_of_call_id=repair_of,
            requested_ids=requested,
        )
        try:
            response = call(requested)
        except InputTooLargeError as exc:
            record.status = "input_too_large"
            records.append(record)
            raise RecoveryExhausted(f"{purpose}: INPUT_TOO_LARGE", records) from exc
        except LlmParseError:
            record.status = "parse_failed"
            records.append(record)
            return call_id, None
        record.model = response.model
        record.prompt_version = response.prompt_version
        record.prompt_hash = response.prompt_hash
        record.usage = response.usage
        records.append(record)
        return call_id, response

    # 1단계: 전체 호출 (구조 오류·파싱 실패 시 전체 재시도)
    pending = list(expected_ids)
    full_call_id = None
    while True:
        full_call_id, response = attempt(None, None)
        if response is None:
            cls = None
        else:
            cls = _classify(expected_ids, [key_fn(item) for item in response.items])
        if response is not None and not cls.structural:
            records[-1].status = "succeeded" if cls.ok else "missing_ids"
            expected_set = set(expected_ids)
            accepted = {
                key_fn(item): item for item in response.items if key_fn(item) in expected_set
            }
            pending = cls.missing
            break
        if response is not None:
            records[-1].status = "schema_invalid"
        if structural_budget == 0:
            raise RecoveryExhausted(f"{purpose}: 구조 오류로 재시도 예산 소진", records)
        structural_budget -= 1

    # 2단계: 누락분만 부분 재호출 (첫 유효 verdict는 유지, 보충 결과만 조인)
    while pending:
        _, response = attempt(list(pending), full_call_id)
        if response is not None:
            cls = _classify(list(pending), [key_fn(item) for item in response.items])
            if not cls.structural and not cls.missing:
                records[-1].status = "succeeded"
                for item in response.items:
                    accepted[key_fn(item)] = item
                pending = []
                break
            records[-1].status = "schema_invalid"
        if structural_budget == 0:
            raise RecoveryExhausted(f"{purpose}: 부분 재호출 실패로 예산 소진", records)
        structural_budget -= 1

    ordered = [accepted[eid] for eid in expected_ids]
    return ordered, records
