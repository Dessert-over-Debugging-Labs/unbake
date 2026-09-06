import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from unbake.adapters.naembii.schema import RecipeCreateRequest, soft_warnings

SEED = Path(__file__).parent / "fixtures" / "seed-recipes.json"


def load_seed():
    return json.loads(SEED.read_text())


def valid_recipe() -> dict:
    return json.loads(json.dumps(load_seed()[0]))  # 순두부찌개 딥카피


def test_seed_recipes_all_valid():
    """실서버 형태의 seed 8건이 전부 스키마를 통과해야 한다."""
    for raw in load_seed():
        RecipeCreateRequest.model_validate(raw)


def test_missing_segment_rejected():
    """⭐ 프로젝트 스펙: 구간 없는 단계는 하드 실패."""
    raw = valid_recipe()
    del raw["steps"][2]["videoStartMs"]
    del raw["steps"][2]["videoEndMs"]
    with pytest.raises(ValidationError):
        RecipeCreateRequest.model_validate(raw)


def test_boundary_overlap_within_limit_allowed():
    """경계 겹침 ≤2초는 허용 (2026-08-06 전환 여유 규칙)."""
    raw = valid_recipe()
    raw["steps"][1]["videoStartMs"] = raw["steps"][0]["videoEndMs"] - 1000  # 1초 겹침
    RecipeCreateRequest.model_validate(raw)


def test_excessive_overlap_rejected():
    raw = valid_recipe()
    raw["steps"][1]["videoStartMs"] = raw["steps"][0]["videoEndMs"] - 3000  # 3초 겹침
    with pytest.raises(ValidationError, match="과도한 겹침"):
        RecipeCreateRequest.model_validate(raw)


def test_nested_segment_rejected():
    """뒤 단계가 앞 단계 안에 완전히 포함되는 중첩은 금지."""
    raw = valid_recipe()
    s0, s1 = raw["steps"][0], raw["steps"][1]
    s0["videoEndMs"] = 30000
    s1["videoStartMs"], s1["videoEndMs"] = 28100, 29000  # s0 내부에 중첩
    with pytest.raises(ValidationError, match="중첩"):
        RecipeCreateRequest.model_validate(raw)


def test_segment_gap_allowed():
    """불연속(사담 스킵)은 허용 — 2026-08-05 스펙."""
    raw = valid_recipe()
    raw["steps"][1]["videoStartMs"] += 3000  # 이전 end와 3초 갭
    RecipeCreateRequest.model_validate(raw)


def test_end_exceeds_duration_rejected():
    raw = valid_recipe()
    raw["steps"][-1]["videoEndMs"] = raw["video"]["durationMs"] + 1
    with pytest.raises(ValidationError, match="영상 길이"):
        RecipeCreateRequest.model_validate(raw)


def test_details_count_bounds():
    raw = valid_recipe()
    raw["steps"][0]["details"] = []
    with pytest.raises(ValidationError):
        RecipeCreateRequest.model_validate(raw)
    raw = valid_recipe()
    raw["steps"][0]["details"] = ["a"] * 5
    with pytest.raises(ValidationError):
        RecipeCreateRequest.model_validate(raw)
    raw = valid_recipe()
    raw["steps"][0]["details"] = ["혼자서도 충분한 단계"]  # 1개 허용
    RecipeCreateRequest.model_validate(raw)


def test_detail_over_300_rejected():
    raw = valid_recipe()
    raw["steps"][0]["details"][0] = "가" * 301
    with pytest.raises(ValidationError, match="300자"):
        RecipeCreateRequest.model_validate(raw)


def test_unknown_enum_rejected():
    raw = valid_recipe()
    raw["difficulty"] = "IMPOSSIBLE"
    with pytest.raises(ValidationError):
        RecipeCreateRequest.model_validate(raw)


def test_empty_arrays_rejected():
    """서버는 빈 배열을 허용하지만 우리는 금지."""
    for key in ["ingredients", "steps", "tags"]:
        raw = valid_recipe()
        raw[key] = []
        with pytest.raises(ValidationError):
            RecipeCreateRequest.model_validate(raw)


def test_soft_warnings_detect():
    raw = valid_recipe()
    step = raw["steps"][0]
    step["videoEndMs"] = step["videoStartMs"] + 45_000  # 45초 구간 (하드 규칙엔 안 걸림)
    step["title"] = "양파 볶고 물 넣기"          # 10자 — 권장 9자 초과, 하드 11자 이내
    raw["steps"] = [step]  # 단계 1개 / 59초 — 평균 59s ≤ 90s라 밀도 경고는 없어야 함
    r = RecipeCreateRequest.model_validate(raw)
    warns = soft_warnings(r)
    assert any("목표" in w for w in warns)          # 구간 30초 초과
    assert any("제목" in w for w in warns)          # 제목 9자 초과
    assert not any("과소" in w or "과밀" in w for w in warns)


def test_density_too_sparse_warns():
    """단계 밀도 (2026-09-05 교체 규칙): durationMs/단계수 > 90초면 과소 경고."""
    raw = valid_recipe()
    raw["video"]["durationMs"] = 500_000  # 500초 / 5단계 = 단계당 100초
    r = RecipeCreateRequest.model_validate(raw)
    assert any("과소" in w for w in soft_warnings(r))


def test_density_too_dense_warns():
    """durationMs/단계수 < 5초면 과밀 경고 — 영상 전체를 써도 단계당 5초가 안 나옴."""
    raw = valid_recipe()  # 59초 영상
    raw["steps"] = [
        {"title": f"단계{i}", "videoStartMs": i * 3900, "videoEndMs": i * 3900 + 3800,
         "details": ["짧은 단계"]}
        for i in range(15)  # 59초 / 15단계 = 단계당 약 3.9초
    ]
    r = RecipeCreateRequest.model_validate(raw)
    assert any("과밀" in w for w in soft_warnings(r))


def test_density_fallback_without_duration():
    """durationMs가 없으면 마지막 구간 end를 영상 길이의 하한으로 쓴다."""
    raw = valid_recipe()
    raw["video"]["durationMs"] = None
    raw["steps"] = [{"title": "한 단계", "videoStartMs": 0, "videoEndMs": 100_000,
                     "details": ["단계 하나로 100초"]}]  # 평균 100초 > 90초
    r = RecipeCreateRequest.model_validate(raw)
    assert any("과소" in w for w in soft_warnings(r))


def test_step_title_over_hard_limit_rejected():
    """단계 제목 11자 초과는 하드 실패 (2026-08-07 규칙)."""
    raw = valid_recipe()
    raw["steps"][0]["title"] = "양파·마늘 볶고 와인 졸이기"   # 15자
    with pytest.raises(ValidationError):
        RecipeCreateRequest.model_validate(raw)


def test_step_title_at_hard_limit_allowed():
    """11자 정확히는 통과 (권장 경고만)."""
    raw = valid_recipe()
    raw["steps"][0]["title"] = "양파 볶고 물 붓기다"          # 11자
    r = RecipeCreateRequest.model_validate(raw)
    assert any("제목" in w for w in soft_warnings(r))


def test_soft_warnings_clean_for_good_recipe():
    r = RecipeCreateRequest.model_validate(valid_recipe())
    assert soft_warnings(r) == []


def test_ingredient_length_warnings():
    """재료명·분량 9자 초과 시 앱 잘림 경고 (2026-08-06 규칙)."""
    raw = valid_recipe()
    raw["ingredients"][0]["name"] = "아주아주아주긴재료이름"       # 11자
    raw["ingredients"][1]["amount"] = "1개 (간 것 반 + 채 썬 것 반)"  # 장문
    r = RecipeCreateRequest.model_validate(raw)
    warns = soft_warnings(r)
    assert any("재료명" in w and "잘림" in w for w in warns)
    assert any("분량" in w and "잘림" in w for w in warns)
    # '영상 참고'는 예외
    raw = valid_recipe()
    raw["ingredients"][0]["amount"] = "영상 참고"
    assert not any("잘림" in w for w in soft_warnings(RecipeCreateRequest.model_validate(raw)))
