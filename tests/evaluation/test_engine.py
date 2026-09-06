from tests.evaluation.conftest import FakeJudge, FakeMatcher, ingredient_fact, make_candidate
from unbake.evaluation.engine import compute_input_hash, evaluate_candidate
from unbake.models import (
    BlindExtraction,
    DescriptionFacts,
    Fact,
    FusedVerdict,
    Severity,
    VideoAction,
)


def _inputs():
    """김치찌개 축소판 — claim 순서: c1 존재(돼지고기), c2 분량(돼지고기 300g),
    c3 존재(설탕), c4 분량(설탕 1큰술, 세부 단계 문장에서)"""
    candidate = make_candidate(
        [
            ("고기 볶기", (0, 60_000), ["돼지고기를 볶는다", "설탕 1큰술을 넣는다"]),
            ("끓이기", (60_000, 180_000), ["물을 붓고 끓인다"]),
        ],
        ingredients=[("돼지고기", "300g"), ("설탕", None)],
        duration_ms=200_000,
    )
    description = DescriptionFacts(facts=[ingredient_fact(None, "돼지고기", "돼지고기 300g")])
    blind = BlindExtraction(
        audio_facts=[Fact(kind="AMOUNT", name="설탕", amount="2큰술", text="설탕 2큰술 넣어주세요")],
        visual_facts=[ingredient_fact(None, "대파", "대파 (자막)")],  # A에 없는 재료 → 누락 후보
        actions=[
            VideoAction(description="고기를 볶는다", start_ms=0, end_ms=30_000),
            VideoAction(description="설탕을 넣는다", start_ms=30_000, end_ms=55_000),
            VideoAction(description="물을 붓는다", start_ms=60_000, end_ms=170_000),
        ],
    )
    return candidate, description, blind


def _judge():
    return FakeJudge(
        {
            "DESCRIPTION": {
                "c1": ("SUPPORTED", None),
                "c2": ("SUPPORTED", None),
            },
            "AUDIO": {
                "c1": ("SUPPORTED", None),
                "c3": ("SUPPORTED", None),
                "c4": ("CONTRADICTED", "2큰술"),  # 음성은 설탕 2큰술이라고 말함
            },
            "VISUAL": {
                "c4": ("SUPPORTED", None),  # 화면 자막은 1큰술 → AUDIO와 충돌
            },
        }
    )


def _matcher():
    return FakeMatcher(
        {
            "s1a": ("MATCHED", ["a1"]),
            "s1b": ("MATCHED", ["a2"]),
            "s2a": ("MATCHED", ["a3"]),
        }
    )


def test_엔진_end_to_end():
    candidate, description, blind = _inputs()
    judge = _judge()
    result, records = evaluate_candidate(
        run_id="run-1",
        candidate=candidate,
        description_facts=description,
        blind=blind,
        judge=judge,
        matcher=_matcher(),
    )

    # 판정은 source당 1회 — 격벽 호출
    assert [c[0] for c in judge.calls] == ["DESCRIPTION", "AUDIO", "VISUAL"]

    by_id = {e.claim_id: e for e in result.claim_evaluations}
    assert by_id["c1"].fused == FusedVerdict.SUPPORTED
    assert by_id["c2"].fused == FusedVerdict.SUPPORTED  # 설명란 단독 SUPPORTED 인정
    assert by_id["c3"].fused == FusedVerdict.SUPPORTED
    # AUDIO CONTRADICTED + VISUAL SUPPORTED → 코드 조인이 CONFLICT 발견
    assert by_id["c4"].fused == FusedVerdict.CONFLICT
    assert by_id["c4"].severity == Severity.MAJOR

    assert result.summary.source_conflict_count == 1
    assert result.summary.contradiction_count == 0
    assert result.summary.matched_step_count == 2
    assert result.summary.unmatched_step_count == 0

    # temporal: s1은 A(0~60s) vs span(0~55s), s2는 A(60~180s) vs span(60~170s)
    assert result.summary.unverified_segment_count == 0
    assert result.summary.suspect_segment_count == 0

    # 화면에만 있던 대파 → 누락 후보 (기록만)
    assert result.summary.omission_count == 1
    assert result.detected_omissions[0].source == "VISUAL"

    # 호출 이력: 판정 3 + 매칭 1
    purposes = [r.purpose for r in records]
    assert purposes == ["judge_description", "judge_audio", "judge_visual", "match_steps"]


def test_유령_fact_참조는_기록하고_제거():
    candidate, description, blind = _inputs()
    judge = _judge()
    original_judge = judge.judge

    def judge_with_ghost(claims, facts, requested):
        resp = original_judge(claims, facts, requested)
        if facts.source == "AUDIO":
            resp.items[0].fact_refs = ["au1", "au999"]  # au999는 없음
        return resp

    judge.judge = judge_with_ghost
    result, _ = evaluate_candidate(
        run_id="run-2",
        candidate=candidate,
        description_facts=description,
        blind=blind,
        judge=judge,
        matcher=_matcher(),
    )
    assert any(i.code == "GHOST_REF" for i in result.validation_issues)
    audio_j = next(
        e.by_source["AUDIO"] for e in result.claim_evaluations if e.claim_id == "c1"
    )
    assert audio_j.fact_refs == ["au1"]


def test_claim이_없으면_판정_호출_생략():
    candidate = make_candidate([("끓이기", (0, 10_000), ["끓인다"])], ingredients=[])
    judge = FakeJudge()
    result, records = evaluate_candidate(
        run_id="run-3",
        candidate=candidate,
        description_facts=DescriptionFacts(),
        blind=BlindExtraction(
            actions=[VideoAction(description="끓인다", start_ms=0, end_ms=10_000)]
        ),
        judge=judge,
        matcher=FakeMatcher({"s1a": ("MATCHED", ["a1"])}),
    )
    assert judge.calls == []
    assert [r.purpose for r in records] == ["match_steps"]
    assert result.claim_evaluations == []


def test_input_hash는_결정적이고_입력에_민감():
    candidate, description, blind = _inputs()
    h1 = compute_input_hash(candidate, description, blind)
    h2 = compute_input_hash(candidate, description, blind)
    assert h1 == h2
    candidate2 = candidate.model_copy(deep=True)
    candidate2.dish_name = "다른찌개"
    assert compute_input_hash(candidate2, description, blind) != h1


def test_B_action이_영상_길이를_넘으면_기록():
    candidate, description, blind = _inputs()
    blind = blind.model_copy(deep=True)
    blind.actions.append(
        VideoAction(description="유령 구간", start_ms=190_000, end_ms=250_000)  # 영상 200s
    )
    result, _ = evaluate_candidate(
        run_id="run-4",
        candidate=candidate,
        description_facts=description,
        blind=blind,
        judge=_judge(),
        matcher=_matcher(),
    )
    assert any(i.code == "ACTION_BEYOND_DURATION" and i.ref == "a4"
               for i in result.validation_issues)


def test_B_action_역전_구간도_기록():
    candidate, description, blind = _inputs()
    blind = blind.model_copy(deep=True)
    blind.actions.append(VideoAction(description="역전", start_ms=50_000, end_ms=50_000))
    result, _ = evaluate_candidate(
        run_id="run-5",
        candidate=candidate,
        description_facts=description,
        blind=blind,
        judge=_judge(),
        matcher=_matcher(),
    )
    assert any(i.code == "ACTION_RANGE_INVALID" for i in result.validation_issues)
