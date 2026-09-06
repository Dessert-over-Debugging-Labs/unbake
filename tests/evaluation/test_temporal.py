from tests.evaluation.conftest import make_candidate
from unbake.evaluation.ids import assign_candidate_ids
from unbake.evaluation.temporal import evaluate_temporal


def _candidate(steps, duration_ms=600_000):
    return assign_candidate_ids(make_candidate(steps, duration_ms=duration_ms))


def test_tIoU_정확값과_half_open():
    c = _candidate([("단계", (0, 10_000), ["문장"])])
    out = evaluate_temporal(c, {"s1": (5_000, 15_000)})
    ev = out.evaluations[0]
    assert ev.intersection_ms == 5_000
    assert ev.union_ms == 15_000
    assert ev.temporal_iou == round(5_000 / 15_000, 4)
    assert ev.start_delta_ms == -5_000
    assert ev.end_delta_ms == -5_000


def test_완전_일치는_tIoU_1():
    c = _candidate([("단계", (1_000, 2_000), ["문장"])])
    out = evaluate_temporal(c, {"s1": (1_000, 2_000)})
    assert out.evaluations[0].temporal_iou == 1.0
    assert out.suspect_count == 0


def test_겹침_없으면_tIoU_0이고_의심_구간():
    c = _candidate([("단계", (0, 5_000), ["문장"])])
    out = evaluate_temporal(c, {"s1": (10_000, 20_000)})
    assert out.evaluations[0].temporal_iou == 0.0
    assert out.suspect_count == 1


def test_매칭된_동작이_없으면_unverified():
    c = _candidate([("단계", (0, 5_000), ["문장"])])
    out = evaluate_temporal(c, {"s1": None})
    ev = out.evaluations[0]
    assert ev.matched is False
    assert ev.temporal_iou is None
    assert out.unverified_count == 1


def test_timestamp_없는_대단계는_unverified():
    c = _candidate([("단계", None, ["문장"])])
    out = evaluate_temporal(c, {"s1": (0, 5_000)})
    assert out.unverified_count == 1


def test_역전_구간은_조용히_보정하지_않고_기록():
    c = _candidate([("단계", (10_000, 3_000), ["문장"])])
    out = evaluate_temporal(c, {"s1": (0, 5_000)})
    assert any(i.code == "RANGE_INVALID" for i in out.issues)
    assert out.evaluations[0].candidate_start_ms is None  # 유효하지 않은 timestamp로는 계산 안 함
    assert out.unverified_count == 1


def test_영상_길이_밖_구간은_기록하되_계산은_계속():
    c = _candidate([("단계", (0, 700_000), ["문장"])], duration_ms=600_000)
    out = evaluate_temporal(c, {"s1": (0, 650_000)})
    assert any(i.code == "BEYOND_DURATION" for i in out.issues)
    assert out.evaluations[0].temporal_iou is not None


def test_중앙값_tIoU():
    c = _candidate(
        [("첫", (0, 10_000), ["a"]), ("둘", (10_000, 20_000), ["b"]), ("셋", (20_000, 30_000), ["c"])]
    )
    out = evaluate_temporal(
        c, {"s1": (0, 10_000), "s2": (10_000, 20_000), "s3": (25_000, 35_000)}
    )
    ious = sorted(e.temporal_iou for e in out.evaluations)
    assert out.median_iou == ious[1]
