"""unbake — YouTube cooking video in, cross-verified structured recipe out.

    from unbake import make_recipe
    artifacts = make_recipe("https://www.youtube.com/watch?v=...")
    artifacts.candidate      # RecipeCandidate: ingredients, steps, sub-steps, timestamps
    artifacts.evaluation     # EvaluationResult: per-claim verdicts, conflicts, temporal IoU

Lower level: `unbake.pipeline.analyze_and_evaluate` takes the five ports directly.
"""

__version__ = "0.2.0"

from unbake.api import OffDomainError, RecipePorts, make_recipe  # noqa: E402
from unbake.models import (  # noqa: E402
    SCHEMA_VERSION,
    BlindExtraction,
    DescriptionFacts,
    EvaluationResult,
    EvaluationSummary,
    RecipeCandidate,
    RunManifest,
)
from unbake.pipeline import AnalysisArtifacts, analyze_and_evaluate, save_artifacts  # noqa: E402

__all__ = [
    "SCHEMA_VERSION",
    "AnalysisArtifacts",
    "BlindExtraction",
    "DescriptionFacts",
    "EvaluationResult",
    "EvaluationSummary",
    "OffDomainError",
    "RecipeCandidate",
    "RecipePorts",
    "RunManifest",
    "__version__",
    "analyze_and_evaluate",
    "make_recipe",
    "save_artifacts",
]
