"""복구 상태기계 golden test — 계약은 docs/architecture.md"""

import pytest

from unbake.evaluation.recovery import (
    InputTooLargeError,
    LlmParseError,
    PortResponse,
    RecoveryExhausted,
    run_batch_with_recovery,
)


class Item:
    def __init__(self, item_id: str, tag: str = ""):
        self.item_id = item_id
        self.tag = tag


def _resp(ids: list[str], tag: str = "") -> PortResponse[Item]:
    return PortResponse(items=[Item(i, tag) for i in ids], model="m", prompt_version="v", prompt_hash="h")


class ScriptedCall:
    """호출 회차별로 미리 짠 응답을 돌려준다."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[list[str] | None] = []

    def __call__(self, requested):
        self.calls.append(requested)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def test_정상_응답은_한번에_끝난다():
    call = ScriptedCall([_resp(["c1", "c2"])])
    items, records = run_batch_with_recovery("judge_test", ["c1", "c2"], call, lambda x: x.item_id)
    assert [i.item_id for i in items] == ["c1", "c2"]
    assert len(records) == 1
    assert records[0].status == "succeeded"
    assert call.calls == [None]


def test_빈_expected는_호출_자체를_안한다():
    call = ScriptedCall([])
    items, records = run_batch_with_recovery("judge_test", [], call, lambda x: x.item_id)
    assert items == [] and records == [] and call.calls == []


def test_누락만_있으면_부분_재호출로_보충():
    call = ScriptedCall([_resp(["c1", "c3"], tag="first"), _resp(["c2"], tag="repair")])
    items, records = run_batch_with_recovery(
        "judge_test", ["c1", "c2", "c3"], call, lambda x: x.item_id
    )
    # 첫 유효 verdict는 유지, 보충 결과만 조인
    assert [(i.item_id, i.tag) for i in items] == [("c1", "first"), ("c2", "repair"), ("c3", "first")]
    assert call.calls == [None, ["c2"]]
    assert records[0].status == "missing_ids"
    assert records[1].status == "succeeded"
    assert records[1].repair_of_call_id == records[0].call_id
    assert records[1].requested_ids == ["c2"]


def test_유령_ID는_전체_재시도():
    call = ScriptedCall([_resp(["c1", "ghost"]), _resp(["c1"])])
    items, records = run_batch_with_recovery("judge_test", ["c1"], call, lambda x: x.item_id)
    assert [i.item_id for i in items] == ["c1"]
    assert records[0].status == "schema_invalid"
    assert call.calls == [None, None]  # 부분이 아니라 전체 재시도


def test_중복_ID는_전체_재시도():
    call = ScriptedCall([_resp(["c1", "c1"]), _resp(["c1"])])
    items, records = run_batch_with_recovery("judge_test", ["c1"], call, lambda x: x.item_id)
    assert records[0].status == "schema_invalid"
    assert len(items) == 1


def test_파싱_실패는_전체_재시도():
    call = ScriptedCall([LlmParseError("깨진 JSON"), _resp(["c1"])])
    items, records = run_batch_with_recovery("judge_test", ["c1"], call, lambda x: x.item_id)
    assert records[0].status == "parse_failed"
    assert [i.item_id for i in items] == ["c1"]


def test_부분_재호출_응답도_전수성_검사():
    call = ScriptedCall(
        [
            _resp(["c1"]),  # c2 누락
            _resp(["c1"]),  # 부분 재호출이 엉뚱한 ID를 반환 → 구조 오류
            _resp(["c2"]),  # 재시도 성공
        ]
    )
    items, records = run_batch_with_recovery("judge_test", ["c1", "c2"], call, lambda x: x.item_id)
    assert [i.item_id for i in items] == ["c1", "c2"]
    assert records[1].status == "schema_invalid"


def test_재시도_예산_소진시_이력과_함께_실패():
    call = ScriptedCall([LlmParseError("1"), LlmParseError("2"), LlmParseError("3")])
    with pytest.raises(RecoveryExhausted) as err:
        run_batch_with_recovery(
            "judge_test", ["c1"], call, lambda x: x.item_id, max_structural_retries=2
        )
    assert len(err.value.records) == 3
    assert all(r.status == "parse_failed" for r in err.value.records)


def test_input_too_large는_재시도_없이_명시적_실패():
    call = ScriptedCall([InputTooLargeError()])
    with pytest.raises(RecoveryExhausted) as err:
        run_batch_with_recovery("judge_test", ["c1"], call, lambda x: x.item_id)
    assert err.value.records[-1].status == "input_too_large"
    assert len(call.calls) == 1  # 재시도 안 함
