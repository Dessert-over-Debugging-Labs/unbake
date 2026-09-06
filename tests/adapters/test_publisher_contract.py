"""naembii adapter가 중립 publishing 계약을 지키는지 — 공통 헬퍼로 검증."""

from tests.adapters.publisher_contract import assert_mapper_contract, assert_publish_result_shape

from unbake.adapters.naembii.mapper import structure_candidate
from unbake.models import CandidateIngredient, CandidateStep, RecipeCandidate, SubStep
from unbake.publishing import PublishResult


def _candidate() -> RecipeCandidate:
    return RecipeCandidate(
        video_id="abc123def45",
        duration_ms=120_000,
        dish_name="애호박볶음",
        title="초간단 애호박볶음",
        summary="아삭한 반찬이에요. 10분 완성해요.",
        servings="2인분",
        cook_time_min=10,
        difficulty="EASY",
        ingredients=[CandidateIngredient(group="MAIN", name="애호박", amount="1개")],
        steps=[
            CandidateStep(
                title="볶기", start_ms=0, end_ms=30_000, sub_steps=[SubStep(text="볶는다")]
            )
        ],
        tags=[{"kind": "CUISINE", "name": "한식"}],
    )


def test_naembii_mapper_계약_준수():
    outcome = assert_mapper_contract(structure_candidate, _candidate())
    assert outcome.errors == []
    assert outcome.payload["video"]["platformVideoId"] == "abc123def45"


def test_naembii_mapper_오류시에도_계약_준수():
    broken = _candidate().model_copy(update={"cook_time_min": None})
    outcome = assert_mapper_contract(structure_candidate, broken)
    assert outcome.errors  # 등록 불가가 errors로 표현된다


def test_publish_result_형태():
    assert_publish_result_shape(PublishResult(status="created", recipe_id="42"))
    assert_publish_result_shape(PublishResult(status="duplicate"))
    assert_publish_result_shape(PublishResult(status="failed", error_code="X"))
