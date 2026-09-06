"""claim 생성 — 후보 레시피에서 검증 가능한 주장을 결정적으로 추출한다.

- 재료 목록: 재료마다 EXISTENCE claim, 분량이 있으면 별도 AMOUNT claim
- 세부 단계 문장: "소금 1작은술" 같은 분량 표현을 정규식으로 추출해 AMOUNT claim
  (근거로 해당 subStepId 참조)
- 동일 (aspect, subject, value) claim은 병합하고 evidence를 합친다
"""

import re

from unbake.models import Claim, ClaimAspect, RecipeCandidate

# 분량으로 인정하는 단위 — 보수적으로 유지하고, 늘릴 때는 golden test와 함께
_UNITS = (
    "큰술|작은술|티스푼|테이블스푼|스푼|컵|종이컵|공기|"
    "그램|킬로그램|리터|밀리리터|g|kg|ml|L|cc|"
    "개|알|모|장|줌|쪽|톨|꼬집|봉지|봉|캔|팩|단|대|뿌리|덩어리|조각|인분"
)
_QTY = r"(?:\d+(?:\.\d+)?(?:\s*/\s*\d+)?|반|한|두|세|네)"
# "소금 1작은술", "설탕 반 스푼" — 재료명(한글/영문) + 수량 + 단위.
# 단위 뒤에는 조사(을/를/이/가…)나 비문자만 올 수 있다 — "1개월" 같은 오탐 방지
_AMOUNT_IN_TEXT = re.compile(
    rf"([가-힣a-zA-Z]{{1,20}})\s*({_QTY}\s*(?:{_UNITS}))"
    r"(?=$|[^가-힣a-zA-Z]|[을를이가은는와과도만씩])"
)

# 분량 미확인 표기 — claim으로 만들지 않는다 (추측 분량 생성 금지 정책의 산물)
_NO_AMOUNT_MARKERS = {"영상 참고", "영상참고"}


def generate_claims(candidate: RecipeCandidate) -> list[Claim]:
    """ID가 부여된 candidate에서 claim 목록을 만든다. claimId는 여기서 부여한다."""
    merged: dict[tuple, Claim] = {}

    def add(aspect: ClaimAspect, subject: str, value: str | None, text: str, ref: str) -> None:
        key = (aspect, subject.strip(), (value or "").strip())
        if key in merged:
            if ref not in merged[key].evidence_refs:
                merged[key].evidence_refs.append(ref)
            return
        merged[key] = Claim(
            claim_id="",  # 마지막에 일괄 부여
            aspect=aspect,
            subject=subject.strip(),
            value=value.strip() if value else None,
            text=text,
            evidence_refs=[ref],
        )

    for ing in candidate.ingredients:
        ref = ing.ingredient_id or ""
        existence_text = f"재료 '{ing.name}'이(가) 이 레시피에 쓰인다"
        add(ClaimAspect.EXISTENCE, ing.name, None, existence_text, ref)
        if ing.amount and ing.amount.strip() not in _NO_AMOUNT_MARKERS:
            add(
                ClaimAspect.AMOUNT,
                ing.name,
                ing.amount,
                f"'{ing.name}'의 분량은 {ing.amount}이다",
                ref,
            )

    for _step, sub in candidate.iter_sub_steps():
        for match in _AMOUNT_IN_TEXT.finditer(sub.text):
            name, amount = match.group(1), match.group(2).strip()
            add(
                ClaimAspect.AMOUNT,
                name,
                amount,
                f"'{name}'의 분량은 {amount}이다",
                sub.sub_step_id or "",
            )

    claims = list(merged.values())
    for ci, claim in enumerate(claims, start=1):
        claim.claim_id = f"c{ci}"
    return claims
