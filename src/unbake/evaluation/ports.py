"""판정·매칭 port — 시그니처가 격벽을 구조적으로 보장한다.

JudgePort는 SourceFacts(자기 source 묶음)만 받는다 — 다른 source를 볼 방법이 없다.
provider는 설정으로 교체 가능하며(judge/matcher 별도), 기본값은 Gemini Flash.
"""

from typing import Protocol

from unbake.evaluation.recovery import PortResponse
from unbake.models import (
    Claim,
    ClaimSourceJudgement,
    RecipeCandidate,
    SourceFacts,
    SubStepMapping,
    VideoAction,
)


class JudgePort(Protocol):
    def judge(
        self,
        claims: list[Claim],
        facts: SourceFacts,
        requested_claim_ids: list[str] | None,
    ) -> PortResponse[ClaimSourceJudgement]:
        """claim 전부(또는 부분 재호출 시 requested만)를 facts와 대조해 판정한다.

        facts는 필터링 없이 전량 입력한다 — 사전 선별이 모순 증거를 놓치면
        CONTRADICTED가 조용히 UNKNOWN으로 샌다 (docs/architecture.md).
        """
        ...


class MatcherPort(Protocol):
    def match(
        self,
        candidate: RecipeCandidate,
        actions: list[VideoAction],
        requested_sub_step_ids: list[str] | None,
    ) -> PortResponse[SubStepMapping]:
        """세부 단계 전부(또는 requested만)를 B의 action과 의미 매칭한다."""
        ...
