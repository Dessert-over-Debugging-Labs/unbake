---
name: build-publish-adapter
description: Assemble a publish adapter for the user's own backend — interview them about endpoints, auth, and duplicate semantics, then implement a mapper + publisher against the neutral contract and verify with the repo's contract tests. Use when someone wants unbake to publish recipes to a backend that has no adapter yet.
---

# Building a publish adapter

Do not restate the contract from memory — it lives in `docs/adapters.md` and
`src/unbake/publishing.py`. The reference implementation is
`src/unbake/adapters/naembii/`. Read all three first.

## 1. Interview the user (only what the code needs)

- Backend name, base URL(s) — separate dev/prod hosts?
- Auth: how is a token obtained? TTL? refresh or re-issue?
- Create endpoint: method/path, required fields, length limits, error format.
- **Duplicate semantics** (ask explicitly): what does a repeated create return
  (status code / error code)? What is the identity key? Should a duplicate
  count as success for their flow?
- Retry safety: idempotency keys? Is retrying a timed-out POST safe?
- Environment variable names for host/secret.

## 2. Implement

Create `src/unbake/adapters/<name>/` with `schema.py` (their DTO + hard rules),
`mapper.py` (candidate → StructureOutcome; never mutate the candidate), and
`client.py` (publisher returning `PublishResult`). Model the *structure* on the
naembii adapter, but take every policy (409 handling, token reuse, round-trip
verification) from the interview answers — naembii's policies are not the
contract.

## 3. Wire and verify

- Wire via `ReviewService(mapper=..., dev_publisher=..., prod_publisher=...)`.
- Tests: reuse `tests/adapters/publisher_contract.py` helpers, then add
  adapter-specific tests for duplicate/auth/error mapping.
- Run `pytest` and `ruff check src tests`. Remind the user that mocked tests
  cannot prove real-server idempotency — suggest one run against their dev
  backend.

## 4. Record decisions

If a policy question came up that future readers will ask about (e.g. "why is
duplicate treated as success here?"), record it via the `decision-log` skill —
as `proposed` unless the human decided it in this session.
