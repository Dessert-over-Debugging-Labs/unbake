"""Neutral publishing contract — what any publish adapter must speak.

An adapter provides two things (see docs/adapters.md):

- a **mapper**: RecipeCandidate (+ optional video meta) → StructureOutcome,
  applying its own deterministic normalization to the mapped copy only
  (the original candidate must never be mutated);
- a **publisher**: payload dict → PublishResult.

Boundary between return and raise: a publisher returns a PublishResult for
outcomes the backend expressed (created / recognized duplicate / rejected).
Transport-level exhaustion (network down, retries spent) may raise instead —
callers treat an exception like a failed result. Duplicate semantics are
backend-specific: confirm what *your* backend returns for a duplicate before
mapping it to "duplicate" (which callers treat as success — idempotency).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

PublishStatus = Literal["created", "duplicate", "failed"]


@dataclass
class PublishResult:
    status: PublishStatus
    recipe_id: str | None = None
    error_code: str | None = None
    message: str | None = None
    field_errors: list | None = None


Publisher = Callable[[dict], PublishResult]


class StructureOutcome(Protocol):
    """What a mapper returns. `payload` is the ready-to-send dict when
    `errors` is empty; `errors` non-empty means the recipe cannot be published
    as-is and must go back to review."""

    payload: dict
    errors: list[str]
    warnings: list[str]
