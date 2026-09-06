"""도메인 모델 — 서비스 중립 IR과 평가 산출물 계약.

직렬화 계약은 전부 camelCase alias(명세 표기)를 쓰고, 파이썬 코드는 snake_case로 접근한다.
시간은 전 계층 정수 ms + half-open [startMs, endMs) (docs/architecture.md).
"""

from unbake.models.base import SCHEMA_VERSION, ApiModel
from unbake.models.candidate import (
    CandidateIngredient,
    CandidateStep,
    RecipeCandidate,
    SubStep,
)
from unbake.models.claims import Claim, ClaimAspect
from unbake.models.evaluation import (
    ClaimEvaluation,
    ClaimSourceJudgement,
    DetectedOmission,
    EvaluationResult,
    EvaluationSummary,
    FusedVerdict,
    Severity,
    Source,
    SourceVerdict,
    StepRollup,
    StepRollupStatus,
    SubStepMapping,
    SubStepMappingStatus,
    TemporalEvaluation,
    ValidationIssue,
)
from unbake.models.facts import (
    BlindExtraction,
    DescriptionFacts,
    Fact,
    SourceFacts,
    VideoAction,
)
from unbake.models.provenance import LlmCallRecord, RunManifest

__all__ = [
    "SCHEMA_VERSION",
    "ApiModel",
    "BlindExtraction",
    "CandidateIngredient",
    "CandidateStep",
    "Claim",
    "ClaimAspect",
    "ClaimEvaluation",
    "ClaimSourceJudgement",
    "DescriptionFacts",
    "DetectedOmission",
    "EvaluationResult",
    "EvaluationSummary",
    "Fact",
    "FusedVerdict",
    "LlmCallRecord",
    "RecipeCandidate",
    "RunManifest",
    "Severity",
    "Source",
    "SourceFacts",
    "SourceVerdict",
    "StepRollup",
    "StepRollupStatus",
    "SubStep",
    "SubStepMapping",
    "SubStepMappingStatus",
    "TemporalEvaluation",
    "ValidationIssue",
    "VideoAction",
]
