from unbake.adapters.naembii.mapper import NO_AMOUNT_TEXT, structure_candidate
from unbake.models import CandidateIngredient, CandidateStep, RecipeCandidate, SubStep


def _candidate(**overrides) -> RecipeCandidate:
    base = dict(
        video_id="abc123def45",
        duration_ms=120_000,
        dish_name="애호박볶음",
        title="초간단 애호박볶음 만들기",
        summary="아삭한 애호박볶음이에요. 10분이면 완성해요.",
        servings="2인분",
        cook_time_min=10,
        difficulty="EASY",
        ingredients=[
            CandidateIngredient(group="MAIN", name="애호박", amount="1개"),
            CandidateIngredient(group="SEASONING", name="소금", amount=None),
            CandidateIngredient(group="SEASONING", name="간장", amount="1 tbsp"),
        ],
        steps=[
            CandidateStep(
                title="절이기",
                start_ms=0,
                end_ms=30_000,
                sub_steps=[SubStep(text="애호박을 채 썬다"), SubStep(text="소금에 절인다")],
            ),
            CandidateStep(
                title="볶기",
                start_ms=30_000,  # 딱 붙은 경계 → 패딩 대상
                end_ms=90_000,
                sub_steps=[SubStep(text="간장 1큰술을 넣고 볶는다")],
            ),
        ],
        tags=[{"kind": "CUISINE", "name": "한식"}],
    )
    base.update(overrides)
    return RecipeCandidate(**base)


def test_정상_매핑과_결정적_후처리():
    candidate = _candidate()
    meta = {"title": "영상 제목", "channelTitle": "채널명"}
    result = structure_candidate(candidate, meta)

    assert result.errors == []
    assert result.request is not None
    req = result.request
    assert req.video.platformVideoId == "abc123def45"
    assert req.video.author == "채널명"
    # 단위 정규화: '1 tbsp' → '1큰술' (DTO에서만 — 원본 candidate는 불변)
    assert req.ingredients[2].amount == "1큰술"
    assert candidate.ingredients[2].amount == "1 tbsp"
    assert result.normalized_units >= 1
    # 딱 붙은 경계(30000==30000)만 +400ms 패딩
    assert req.steps[0].videoEndMs == 30_400
    assert candidate.steps[0].end_ms == 30_000
    assert result.padded_boundaries == 1
    # 분량 미확인 → '영상 참고'
    assert req.ingredients[1].amount == NO_AMOUNT_TEXT


def test_필수값_없으면_등록불가_에러로_보고():
    result = structure_candidate(_candidate(cook_time_min=None, summary=None))
    assert result.request is None
    joined = " / ".join(result.errors)
    assert "cookTimeMin" in joined
    assert "summary" in joined


def test_세부단계_5개는_details_하드_규칙_위반():
    step = CandidateStep(
        title="과밀",
        start_ms=0,
        end_ms=30_000,
        sub_steps=[SubStep(text=f"동작 {i}") for i in range(5)],
    )
    result = structure_candidate(_candidate(steps=[step]))
    assert result.request is None
    assert any("details" in e for e in result.errors)


def test_태그_없으면_ETC_폴백과_경고():
    result = structure_candidate(_candidate(tags=[]))
    assert result.request is not None
    assert result.request.tags[0].kind == "ETC"
    assert any("태그 없음" in w for w in result.warnings)


def test_알수없는_group은_MAIN_정규화_후_경고():
    result = structure_candidate(
        _candidate(ingredients=[CandidateIngredient(group="ETC", name="두부", amount="1모")])
    )
    assert result.request is not None
    assert result.request.ingredients[0].group == "MAIN"
    assert any("두부" in w for w in result.warnings)
