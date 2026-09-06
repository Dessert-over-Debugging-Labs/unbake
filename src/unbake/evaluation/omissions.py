"""누락 후보 탐지 — 설명란/B에는 있는데 A 레시피에는 없는 사실.

초기에는 기록·표시만 한다 — 자동 탈락 기준이 아니다 (docs/architecture.md).
v1은 결정적 재료명 대조만 수행한다. 판정 LLM의 missingClaims 병합은 M2에서.
"""

import re

from unbake.models import (
    BlindExtraction,
    Claim,
    ClaimAspect,
    DescriptionFacts,
    DetectedOmission,
    Fact,
    Source,
)


def _norm(name: str) -> str:
    return "".join(name.split()).lower()


def _sub_names(name: str) -> list[str]:
    """복합 표기('마요네즈, 치즈, 파슬리')를 재료 단위로 쪼갠다 —
    통짜 비교는 전부 미스가 나서 누락 후보 오탐을 만든다 (2026-09-05 smoke)."""
    return [_norm(part) for part in re.split(r"[,·/]", name) if part.strip()]


def detect_omissions(
    claims: list[Claim],
    description_facts: DescriptionFacts,
    blind: BlindExtraction,
) -> list[DetectedOmission]:
    known = {
        _norm(c.subject) for c in claims if c.aspect == ClaimAspect.EXISTENCE
    }
    omissions: list[DetectedOmission] = []
    seen: set[tuple[Source, str]] = set()

    def scan(facts: list[Fact], source: Source) -> None:
        for fact in facts:
            if fact.kind != "INGREDIENT" or not fact.name:
                continue
            missing = [n for n in _sub_names(fact.name) if n not in known]
            key = (source, tuple(missing))
            if not missing or key in seen:
                continue
            seen.add(key)
            omissions.append(
                DetectedOmission(
                    source=source,
                    kind="INGREDIENT",
                    text=f"{', '.join(missing)} — {fact.text}",
                    fact_refs=[fact.fact_id] if fact.fact_id else [],
                )
            )

    scan(description_facts.facts, Source.DESCRIPTION)
    scan(blind.audio_facts, Source.AUDIO)
    scan(blind.visual_facts, Source.VISUAL)
    return omissions
