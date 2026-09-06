"""Gemini 판정·매칭 — 텍스트만 입력하는 저렴한 호출.

JudgePort 구현은 SourceFacts 하나만 받는다 — source 격벽은 시그니처가 보장한다.
facts는 필터링 없이 전량 넣는다 (사전 선별이 모순 증거를 놓치면
CONTRADICTED가 조용히 UNKNOWN으로 샌다).
"""

import json

from pydantic import ValidationError

from unbake.adapters.gemini.client import GeminiClient
from unbake.evaluation.recovery import LlmParseError, PortResponse
from unbake.extraction.prompt_store import load_prompt
from unbake.models import (
    Claim,
    ClaimSourceJudgement,
    RecipeCandidate,
    SourceFacts,
    SubStepMapping,
    VideoAction,
)


def _dumps(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False, indent=1)


class GeminiJudge:
    def __init__(self, client: GeminiClient, model: str):
        self._client = client
        self._model = model
        self._prompt = load_prompt("judge")

    def judge(
        self,
        claims: list[Claim],
        facts: SourceFacts,
        requested_claim_ids: list[str] | None,
    ) -> PortResponse[ClaimSourceJudgement]:
        wanted = (
            [c for c in claims if c.claim_id in set(requested_claim_ids)]
            if requested_claim_ids
            else claims
        )
        rendered = self._prompt.render(
            SOURCE=facts.source,
            FACTS_JSON=_dumps([f.dump() for f in facts.facts]),
            CLAIMS_JSON=_dumps([c.dump() for c in wanted]),
        )
        data, usage = self._client.generate_json(self._model, rendered)
        if not isinstance(data, list):
            raise LlmParseError("판정 응답이 배열이 아니다")
        try:
            items = [ClaimSourceJudgement.model_validate(x) for x in data]
        except ValidationError as exc:
            raise LlmParseError(f"판정 계약 위반: {exc}") from exc
        return PortResponse(
            items=items,
            model=self._model,
            prompt_version=self._prompt.version,
            prompt_hash=self._prompt.hash,
            usage=usage,
        )


class GeminiMatcher:
    def __init__(self, client: GeminiClient, model: str):
        self._client = client
        self._model = model
        self._prompt = load_prompt("matcher")

    def match(
        self,
        candidate: RecipeCandidate,
        actions: list[VideoAction],
        requested_sub_step_ids: list[str] | None,
    ) -> PortResponse[SubStepMapping]:
        wanted = set(requested_sub_step_ids) if requested_sub_step_ids else None
        sub_steps = [
            {
                "subStepId": sub.sub_step_id,
                "stepId": step.step_id,
                "stepTitle": step.title,
                "text": sub.text,
            }
            for step, sub in candidate.iter_sub_steps()
            if wanted is None or sub.sub_step_id in wanted
        ]
        rendered = self._prompt.render(
            SUB_STEPS_JSON=_dumps(sub_steps),
            ACTIONS_JSON=_dumps([a.dump() for a in actions]),
        )
        data, usage = self._client.generate_json(self._model, rendered)
        if not isinstance(data, list):
            raise LlmParseError("매칭 응답이 배열이 아니다")
        try:
            items = [SubStepMapping.model_validate(x) for x in data]
        except ValidationError as exc:
            raise LlmParseError(f"매칭 계약 위반: {exc}") from exc
        return PortResponse(
            items=items,
            model=self._model,
            prompt_version=self._prompt.version,
            prompt_hash=self._prompt.hash,
            usage=usage,
        )
