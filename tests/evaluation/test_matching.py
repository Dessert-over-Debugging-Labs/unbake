from tests.evaluation.conftest import make_actions, make_candidate
from unbake.evaluation.ids import assign_candidate_ids
from unbake.evaluation.matching import validate_and_rollup
from unbake.models import StepRollupStatus, SubStepMapping, SubStepMappingStatus


def _proposals(spec: dict[str, tuple[str, list[str]]]) -> list[SubStepMapping]:
    return [
        SubStepMapping(sub_step_id=sid, status=status, action_ids=aids)
        for sid, (status, aids) in spec.items()
    ]


def _candidate(steps):
    return assign_candidate_ids(make_candidate(steps))


def test_전부_일치하면_MATCHED_롤업():
    c = _candidate([("절이기", (0, 12_000), ["채 썬다", "버무린다"])])
    actions = make_actions([(0, 5_000), (5_000, 12_000)])
    out = validate_and_rollup(
        c, actions, _proposals({"s1a": ("MATCHED", ["a1"]), "s1b": ("MATCHED", ["a2"])})
    )
    assert out.rollups[0].status == StepRollupStatus.MATCHED
    assert out.step_spans["s1"] == (0, 12_000)


def test_일부만_일치하면_PARTIAL():
    c = _candidate([("절이기", (0, 12_000), ["채 썬다", "버무린다"])])
    actions = make_actions([(0, 5_000)])
    out = validate_and_rollup(
        c, actions, _proposals({"s1a": ("MATCHED", ["a1"]), "s1b": ("UNMATCHED", [])})
    )
    assert out.rollups[0].status == StepRollupStatus.PARTIAL


def test_하나도_일치_안하면_UNMATCHED():
    c = _candidate([("절이기", (0, 12_000), ["채 썬다"])])
    out = validate_and_rollup(c, [], _proposals({"s1a": ("UNMATCHED", [])}))
    assert out.rollups[0].status == StepRollupStatus.UNMATCHED
    assert out.step_spans["s1"] is None


def test_UNOBSERVABLE은_패널티_없이_제외():
    # "10분 그대로 절인다" — 점프컷으로 사라지는 대기 단계
    c = _candidate([("절이기", (0, 12_000), ["버무린다", "10분 그대로 절인다"])])
    actions = make_actions([(0, 12_000)])
    out = validate_and_rollup(
        c, actions, _proposals({"s1a": ("MATCHED", ["a1"]), "s1b": ("UNOBSERVABLE", [])})
    )
    assert out.rollups[0].status == StepRollupStatus.MATCHED  # UNOBSERVABLE이 롤업을 깎지 않음
    assert out.rollups[0].unobservable_count == 1


def test_관찰가능_세부단계가_없는_대단계는_패널티_없음():
    c = _candidate([("숙성", (0, 60_000), ["냉장고에서 하루 숙성한다"])])
    out = validate_and_rollup(c, [], _proposals({"s1a": ("UNOBSERVABLE", [])}))
    assert out.rollups[0].status == StepRollupStatus.MATCHED
    assert out.rollups[0].unobservable_only is True


def test_세부단계_하나가_연속_action_여러개와_매칭():
    c = _candidate([("볶기", (0, 30_000), ["재료를 넣고 볶는다"])])
    actions = make_actions([(0, 10_000), (10_000, 20_000), (20_000, 30_000)])
    out = validate_and_rollup(c, actions, _proposals({"s1a": ("MATCHED", ["a1", "a2", "a3"])}))
    assert out.mappings[0].violations == []
    assert out.step_spans["s1"] == (0, 30_000)


def test_비연속_action_매칭은_위반_기록():
    c = _candidate([("볶기", (0, 30_000), ["볶는다"])])
    actions = make_actions([(0, 10_000), (10_000, 20_000), (20_000, 30_000)])
    out = validate_and_rollup(c, actions, _proposals({"s1a": ("MATCHED", ["a1", "a3"])}))
    assert "non_contiguous" in out.mappings[0].violations
    assert out.mappings[0].status == SubStepMappingStatus.MATCHED  # 강등은 안 함


def test_유령_action_참조는_기록하고_제거():
    c = _candidate([("볶기", (0, 30_000), ["볶는다"])])
    actions = make_actions([(0, 10_000)])
    out = validate_and_rollup(c, actions, _proposals({"s1a": ("MATCHED", ["a1", "a99"])}))
    assert out.mappings[0].action_ids == ["a1"]
    assert any(i.code == "GHOST_REF" for i in out.issues)


def test_근거_없는_MATCHED는_UNMATCHED로_강등():
    c = _candidate([("볶기", (0, 30_000), ["볶는다"])])
    out = validate_and_rollup(c, [], _proposals({"s1a": ("MATCHED", [])}))
    assert out.mappings[0].status == SubStepMappingStatus.UNMATCHED
    assert "matched_without_action" in out.mappings[0].violations


def test_action_공유_비인접이면_위반():
    c = _candidate(
        [("손질", (0, 10_000), ["썬다", "다진다", "헹군다"])]
    )
    actions = make_actions([(0, 10_000)])
    out = validate_and_rollup(
        c,
        actions,
        _proposals(
            {
                "s1a": ("MATCHED", ["a1"]),
                "s1b": ("UNMATCHED", []),
                "s1c": ("MATCHED", ["a1"]),  # s1a와 비인접 공유
            }
        ),
    )
    assert any(i.code == "SHARED_ACTION" for i in out.issues)
    assert "shared_action_nonadjacent" in out.mappings[0].violations


def test_action_공유_인접이면_flag만():
    c = _candidate([("손질", (0, 10_000), ["썰고", "바로 볶는다"])])
    actions = make_actions([(0, 10_000)])
    out = validate_and_rollup(
        c, actions, _proposals({"s1a": ("MATCHED", ["a1"]), "s1b": ("MATCHED", ["a1"])})
    )
    assert all(i.code != "SHARED_ACTION" for i in out.issues)
    assert "shared_action_adjacent" in out.mappings[0].violations


def test_대단계_내_역순은_ORDER_CONFLICT():
    c = _candidate([("조리", (0, 30_000), ["먼저 한다", "나중에 한다"])])
    actions = make_actions([(20_000, 30_000), (0, 10_000)])
    out = validate_and_rollup(
        c, actions, _proposals({"s1a": ("MATCHED", ["a1"]), "s1b": ("MATCHED", ["a2"])})
    )
    assert out.rollups[0].status == StepRollupStatus.ORDER_CONFLICT


def test_대단계_간_역순은_뒤_단계에_ORDER_CONFLICT():
    c = _candidate(
        [("먼저", (0, 10_000), ["A를 한다"]), ("나중", (10_000, 20_000), ["B를 한다"])]
    )
    actions = make_actions([(15_000, 20_000), (0, 5_000)])
    out = validate_and_rollup(
        c, actions, _proposals({"s1a": ("MATCHED", ["a1"]), "s2a": ("MATCHED", ["a2"])})
    )
    assert out.rollups[0].status == StepRollupStatus.MATCHED
    assert out.rollups[1].status == StepRollupStatus.ORDER_CONFLICT


def test_겹치는_span은_순서_충돌_아님():
    # 겹침은 자동 역순 처리하지 않는다
    c = _candidate([("동시", (0, 20_000), ["A를 하며", "B도 한다"])])
    actions = make_actions([(0, 15_000), (5_000, 20_000)])
    out = validate_and_rollup(
        c, actions, _proposals({"s1a": ("MATCHED", ["a2"]), "s1b": ("MATCHED", ["a1"])})
    )
    # s1b의 span(0~15s)이 s1a의 span(5~20s)과 겹침 — 분리된 역순이 아니므로 충돌 없음
    assert out.rollups[0].status == StepRollupStatus.MATCHED
