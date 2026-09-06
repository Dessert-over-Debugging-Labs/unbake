"""RecipeCreateRequest 스키마 — 냄비 백엔드 스펙 + 프로젝트 하드 규칙의 코드화.

- 하드 규칙 위반 = ValidationError (⑤ structure에서 재보정 1회 트리거)
- 소프트 권장치(구간 5~30초, 제목 9자·details 40자, 단계 밀도)는 soft_warnings()로
  분리 — 차단하지 않음
"""
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class Platform(StrEnum):
    YOUTUBE = "YOUTUBE"
    INSTAGRAM = "INSTAGRAM"
    TIKTOK = "TIKTOK"


class Difficulty(StrEnum):
    EASY = "EASY"
    NORMAL = "NORMAL"
    HARD = "HARD"


class IngredientGroup(StrEnum):
    MAIN = "MAIN"
    SEASONING = "SEASONING"


class TagKind(StrEnum):
    CUISINE = "CUISINE"
    FLAVOR = "FLAVOR"
    TEMPERATURE = "TEMPERATURE"
    ETC = "ETC"


class VideoRequest(BaseModel):
    platform: Platform
    url: str = Field(min_length=1, max_length=500)
    platformVideoId: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=200)
    author: str | None = Field(default=None, max_length=100)
    thumbnailUrl: str | None = Field(default=None, max_length=500)
    durationMs: int | None = Field(default=None, gt=0)


class IngredientRequest(BaseModel):
    group: IngredientGroup
    name: str = Field(min_length=1, max_length=100)
    amount: str | None = Field(default=None, max_length=50)


# 단계 제목 상한 (2026-08-07 확정 — 백엔드는 100자까지 받지만 프로젝트 규칙으로 조인다)
STEP_TITLE_LIMIT = 11


class StepRequest(BaseModel):
    title: str = Field(min_length=1, max_length=STEP_TITLE_LIMIT)
    # ⭐ 프로젝트 스펙: 모든 단계에 구간 필수 (백엔드는 optional이지만 우리는 강제)
    videoStartMs: int = Field(ge=0)
    videoEndMs: int = Field(gt=0)
    details: list[str] = Field(min_length=1, max_length=4)  # 단계당 1~4개

    @field_validator("details")
    @classmethod
    def details_len(cls, v: list[str]) -> list[str]:
        for i, t in enumerate(v):
            if not t.strip():
                raise ValueError(f"details[{i}]가 비어 있음")
            if len(t) > 300:
                raise ValueError(f"details[{i}]가 300자 초과 ({len(t)}자)")
        return v

    @model_validator(mode="after")
    def range_valid(self) -> "StepRequest":
        if not (0 <= self.videoStartMs < self.videoEndMs):
            raise ValueError(
                f"구간 규칙 위반: 0 <= start({self.videoStartMs}) < end({self.videoEndMs})")
        return self


class TagRequest(BaseModel):
    kind: TagKind
    name: str = Field(min_length=1, max_length=50)


class RecipeCreateRequest(BaseModel):
    video: VideoRequest
    dishName: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=500)
    servings: str = Field(min_length=1, max_length=30)
    cookTimeMin: int = Field(gt=0)
    difficulty: Difficulty
    ingredients: list[IngredientRequest] = Field(min_length=1)
    steps: list[StepRequest] = Field(min_length=1)
    tags: list[TagRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def segments_ordered(self) -> "RecipeCreateRequest":
        """구간 규칙 (2026-08-06 갱신): start·end 각각 단조 증가, 경계 겹침은
        BOUNDARY_OVERLAP_MAX_MS까지 허용 (전환 여유 — 자막/장면 타이밍 어긋남 흡수),
        불연속 허용, end <= durationMs."""
        prev_start = prev_end = None
        for i, s in enumerate(self.steps):
            if prev_start is not None:
                if s.videoStartMs <= prev_start:
                    raise ValueError(
                        f"steps[{i}] 순서 역전: start({s.videoStartMs})"
                        f" <= 이전 start({prev_start})")
                if s.videoEndMs <= prev_end:
                    raise ValueError(
                        f"steps[{i}] 구간 중첩: end({s.videoEndMs}) <= 이전 end({prev_end})")
                if s.videoStartMs < prev_end - BOUNDARY_OVERLAP_MAX_MS:
                    raise ValueError(
                        f"steps[{i}] 과도한 겹침: start({s.videoStartMs})가"
                        f" 이전 end({prev_end})보다 {BOUNDARY_OVERLAP_MAX_MS}ms 이상 앞섬")
            prev_start, prev_end = s.videoStartMs, s.videoEndMs
        dur = self.video.durationMs
        if dur is not None:
            last = self.steps[-1].videoEndMs
            if last > dur:
                raise ValueError(f"마지막 구간 end({last})가 영상 길이({dur}) 초과")
        return self


# 인접 단계 경계 겹침 허용 한도 (2026-08-06 확정 — 전환 여유, 권장 0.5~1초)
BOUNDARY_OVERLAP_MAX_MS = 2_000

# ---- 소프트 권장치 — 차단하지 않고 보고만 ----

SEG_MIN_MS, SEG_MAX_MS = 5_000, 30_000
# 단계 제목: 권장 ≤9자 / 하드 상한 STEP_TITLE_LIMIT(11자) — 상한은 스키마가 차단한다
STEP_TITLE_MAX, DETAIL_MAX = 9, 40
# 단계 밀도 (2026-09-05 교체 — docs/architecture.md): 고정 4~8개 대신 영상 길이 대비
# 단계당 평균 시간(durationMs/단계수)으로 판단한다.
# - 하한: 평균이 SEG_MIN_MS(5초) 미만이면 영상 전체를 써도 단계당 5초가 안 나옴 → 과밀
# - 상한: 인트로·사담 등 비레시피 구간을 감안해 SEG_MAX_MS의 3배(90초)까지 허용 → 초과는 과소
DENSITY_MIN_MS = SEG_MIN_MS
DENSITY_MAX_MS = SEG_MAX_MS * 3
# 재료명·분량: 앱 셀이 9자 초과를 '...'로 자름 (2026-08-06 확정) — 적정 1~7자
ING_TEXT_MAX = 9


def soft_warnings(r: RecipeCreateRequest) -> list[str]:
    warns: list[str] = []
    # 단계 밀도 — durationMs 없으면 마지막 구간 end(영상 길이의 하한)로 대신한다
    dur = r.video.durationMs or r.steps[-1].videoEndMs
    avg_ms = dur / len(r.steps)
    if avg_ms < DENSITY_MIN_MS:
        warns.append(
            f"단계 {len(r.steps)}개 — 영상 {dur/1000:.0f}초 대비 과밀 "
            f"(단계당 평균 {avg_ms/1000:.1f}s < {DENSITY_MIN_MS/1000:.0f}s)")
    elif avg_ms > DENSITY_MAX_MS:
        warns.append(
            f"단계 {len(r.steps)}개 — 영상 {dur/1000:.0f}초 대비 과소 "
            f"(단계당 평균 {avg_ms/1000:.0f}s > {DENSITY_MAX_MS/1000:.0f}s)")
    for i, s in enumerate(r.steps):
        length = s.videoEndMs - s.videoStartMs
        if length > SEG_MAX_MS:
            warns.append(f"steps[{i}] '{s.title}' 구간 {length/1000:.0f}s — 목표 5~30초 초과")
        elif length < SEG_MIN_MS:
            warns.append(f"steps[{i}] '{s.title}' 구간 {length/1000:.1f}s — 5초 미만")
        if len(s.title) > STEP_TITLE_MAX:
            warns.append(f"steps[{i}] 제목 {len(s.title)}자 — 권장 ≤{STEP_TITLE_MAX}자")
        for j, d in enumerate(s.details):
            if len(d) > DETAIL_MAX:
                warns.append(f"steps[{i}].details[{j}] {len(d)}자 — 권장 ≤{DETAIL_MAX}자")
    for ing in r.ingredients:
        if len(ing.name) > ING_TEXT_MAX:
            warns.append(f"재료명 '{ing.name}' {len(ing.name)}자 — 앱에서 …로 잘림"
                         f" (최대 {ING_TEXT_MAX}자, 적정 1~7자)")
        if ing.amount and len(ing.amount) > ING_TEXT_MAX and ing.amount != "영상 참고":
            warns.append(f"'{ing.name}' 분량 '{ing.amount}' {len(ing.amount)}자"
                         f" — 앱에서 …로 잘림 (적정 1~7자)")
    return warns
