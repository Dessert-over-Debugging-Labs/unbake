"""Repo-managed contract checks for publish adapters (see docs/adapters.md).

A new adapter's tests should call these helpers instead of re-stating the
contract — if the same author (human or agent) writes both the implementation
and its expectations, they can share the same misconception. These checks are
the house rules.

Limits: mocked tests cannot prove real-server idempotency or auth behavior.
Verify against the backend's dev environment before relying on an adapter.
"""

VALID_STATUSES = {"created", "duplicate", "failed"}


def assert_publish_result_shape(result) -> None:
    """Every publisher return must be a valid PublishResult."""
    assert result.status in VALID_STATUSES, f"unknown status: {result.status!r}"
    if result.status == "created":
        assert result.recipe_id, "a 'created' result must carry recipe_id"
    if result.status == "failed":
        assert result.error_code or result.message, "a 'failed' result must say why"


def assert_mapper_contract(mapper, candidate, video_meta=None):
    """Mapper must not mutate the candidate and must expose payload/errors/warnings.

    Returns the outcome so the caller can add adapter-specific assertions.
    """
    before = candidate.model_dump()
    outcome = mapper(candidate, video_meta)
    assert candidate.model_dump() == before, "mapper mutated the original candidate IR"
    assert isinstance(outcome.errors, list)
    assert isinstance(outcome.warnings, list)
    if not outcome.errors:
        assert isinstance(outcome.payload, dict) and outcome.payload, (
            "no errors but payload is empty — the mapper must produce a sendable dict"
        )
    return outcome
