# Writing a publish adapter

unbake ends by handing a verified, human-approved recipe to *some* backend.
That last hop is an adapter, and it is deliberately small: **a mapper and a
publisher**. Everything upstream (extraction, evaluation, review) runs without
any adapter configured.

The neutral contract lives in `src/unbake/publishing.py`. The working
reference implementation is `src/unbake/adapters/naembii/` — read it, but
treat its *policies* as backend-specific (see below).

## The contract

### 1. Mapper — `(candidate, video_meta) -> StructureOutcome`

Takes the approved `RecipeCandidate` (plus optional video metadata) and
produces:

- `payload: dict` — the ready-to-send request body, when `errors` is empty;
- `errors: list[str]` — hard-rule violations; a non-empty list means the recipe
  goes back to review, it is never "fixed up" and sent anyway;
- `warnings: list[str]` — soft findings, surfaced to the reviewer.

Rules: the mapper must **never mutate the original candidate** — deterministic
normalization (units, boundary padding, …) applies to the mapped copy only.

### 2. Publisher — `(payload: dict) -> PublishResult`

`PublishResult.status` is one of `created | duplicate | failed`.

- Return a result for outcomes the backend expressed (created, recognized
  duplicate, rejected payload).
- Raising is acceptable for transport-level exhaustion (network down, retry
  budget spent) — callers treat an exception like a failure.
- **Duplicate semantics are yours to confirm.** Callers treat `duplicate` as
  idempotent success. Before mapping any response to `duplicate`, check what
  your backend actually returns for a repeated create and what its identity
  key is. If the backend gives no idempotency guarantee, do not blindly retry
  a timed-out POST.

### 3. Wiring

```python
from unbake.review.service import ReviewService

service = ReviewService(
    db_path, output_dir,
    mapper=my_structure_candidate,     # defaults to the naembii mapper
    dev_publisher=my_dev_publish,      # payload dict -> PublishResult
    prod_publisher=my_prod_publish,
)
```

The review flow guarantees: only human-approved revisions reach the mapper,
and production publishing happens only through an explicit human action.

## What is naembii policy, not contract

The reference adapter makes choices that fit its backend — copy them only if
they fit yours:

- HTTP 409 → `duplicate`, treated as success (that backend keys duplicates on
  the video ID);
- admin token issued per session, reused for 25 minutes, one re-issue on 401;
- post-create round-trip verification (`GET` the created recipe and compare);
- Korean unit normalization and field-length rules in the mapper.

## Testing

Reuse the repo-managed checks in `tests/adapters/publisher_contract.py`
(`assert_mapper_contract`, `assert_publish_result_shape`) and add
adapter-specific tests for your duplicate/auth/error mapping. Mocked tests
cannot prove real-server idempotency — verify against your backend's dev
environment before trusting the adapter.

If you use a coding agent, the `build-publish-adapter` skill
(`.claude/skills/build-publish-adapter/`) walks it through an interview and
this checklist.
