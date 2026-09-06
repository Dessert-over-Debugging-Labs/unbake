"""⑤ 구조화 — RecipeCandidate(IR) → RecipeCreateRequest(냄비 백엔드 DTO).

결정적 normalization(단위 정규화·경계 패딩)은 여기서만 적용한다 —
원본 candidate(평가·revision 대상)는 건드리지 않는다 (docs/architecture.md).
하드 규칙 위반은 조용히 고치지 않고 errors로 보고해 검수 화면에 띄운다.
"""

from dataclasses import dataclass, field

from pydantic import ValidationError

from unbake.adapters.naembii.schema import RecipeCreateRequest, soft_warnings
from unbake.models import RecipeCandidate
from unbake.normalize import apply_boundary_padding, normalize_units

# 분량 미확인 표기 (과거 실측)
NO_AMOUNT_TEXT = "영상 참고"

_VALID_GROUPS = {"MAIN", "SEASONING"}
_VALID_TAG_KINDS = {"CUISINE", "FLAVOR", "TEMPERATURE", "ETC"}
_VALID_DIFFICULTY = {"EASY", "NORMAL", "HARD"}


@dataclass
class StructureResult:
    request: RecipeCreateRequest | None  # 하드 규칙 통과 시에만
    payload: dict = field(default_factory=dict)  # 정규화 적용된 DTO dict (검수·수정용)
    errors: list[str] = field(default_factory=list)  # 하드 규칙 위반 — 등록 불가
    warnings: list[str] = field(default_factory=list)  # 소프트 권장치 — 표시만
    normalized_units: int = 0
    padded_boundaries: int = 0


def structure_candidate(
    candidate: RecipeCandidate, video_meta: dict | None = None
) -> StructureResult:
    """video_meta: adapters.youtube.videos.get_video_meta() 결과 (없어도 동작)."""
    meta = video_meta or {}
    result = StructureResult(request=None)

    ingredients = []
    for ing in candidate.ingredients:
        group = ing.group if ing.group in _VALID_GROUPS else "MAIN"
        if ing.group not in _VALID_GROUPS:
            result.warnings.append(f"재료 '{ing.name}' group '{ing.group}' → MAIN으로 정규화")
        ingredients.append(
            {"group": group, "name": ing.name, "amount": ing.amount or NO_AMOUNT_TEXT}
        )

    steps = []
    for step in candidate.steps:
        steps.append(
            {
                "title": step.title,
                "videoStartMs": step.start_ms,
                "videoEndMs": step.end_ms,
                "details": [s.text for s in step.sub_steps if s.text.strip()],
            }
        )

    tags = []
    for tag in candidate.tags:
        kind = tag.get("kind")
        name = tag.get("name")
        if kind in _VALID_TAG_KINDS and name:
            tags.append({"kind": kind, "name": name})
    if not tags:
        tags = [{"kind": "ETC", "name": candidate.dish_name[:50]}]
        result.warnings.append("태그 없음 — dishName으로 ETC 태그 생성")

    payload = {
        "video": {
            "platform": "YOUTUBE",
            "url": f"https://www.youtube.com/watch?v={candidate.video_id}",
            "platformVideoId": candidate.video_id,
            "title": meta.get("title") or candidate.title,
            "author": meta.get("channelTitle"),
            "thumbnailUrl": meta.get("thumbnailUrl"),
            "durationMs": candidate.duration_ms,
        },
        "dishName": candidate.dish_name,
        "title": candidate.title or f"{candidate.dish_name} 만들기",
        "summary": candidate.summary,
        "servings": candidate.servings or NO_AMOUNT_TEXT,
        "cookTimeMin": candidate.cook_time_min,
        "difficulty": candidate.difficulty if candidate.difficulty in _VALID_DIFFICULTY else None,
        "ingredients": ingredients,
        "steps": steps,
        "tags": tags,
    }

    # 결정적 후처리 — DTO 사본에만 적용, candidate 원본은 불변
    result.normalized_units = normalize_units(payload)
    result.padded_boundaries = apply_boundary_padding(payload)
    result.payload = payload

    try:
        request = RecipeCreateRequest.model_validate(payload)
    except ValidationError as exc:
        result.errors = [
            f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()
        ]
        return result

    result.request = request
    # payload를 검증 통과본(전송 형식)으로 확정 — 중립 계약(StructureOutcome)의 표면
    result.payload = request.model_dump(exclude_none=True)
    result.warnings.extend(soft_warnings(request))
    return result
