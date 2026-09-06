# Architecture

unbake extracts a structured recipe from a cooking video, then **verifies it**
by cross-checking independent extractions with deterministic code. The design
premise: a model's self-reported confidence is not evidence. Verification comes
from independence and joins, not from asking the extractor how sure it is.

## Scope

```
video URL → gate → extract → evaluate → artifacts
```

The library ends at the artifacts. Discovering videos, queueing, human review,
and publishing are application concerns built on top of the artifact schema and
the quality-event log — they are deliberately not in this package.

- **gate** — before any video is sent to a model, a text-only judge reads the
  title, channel, and description and decides whether this is a cooking video
  at all. It runs on a cheap OpenRouter model by default or on Gemini. A
  rejected video never reaches extraction; a judge failure is an error, never a
  silent pass. The threshold lives in code, not in the prompt.
- **extract** — three independent LLM extractions per video (see below).
- **evaluate** — deterministic cross-validation producing per-claim verdicts,
  step matching, and temporal metrics.

`make_recipe()` (`api.py`) assembles the default Gemini ports from config and
runs `analyze_and_evaluate()` (`pipeline.py`), which takes the five ports
directly and knows nothing about providers.

## Extraction: two views plus the description

```
Generator A        video + description → recipe candidate (hierarchical IR)
Blind observer B   video only          → audio facts, visual facts, timed actions
Description parser description only    → description facts
```

B never sees A's output or the description — its function signature only accepts
a video reference, so the isolation is structural, not a prompt instruction.
Videos are analyzed directly from their URL (Gemini video input); nothing is
downloaded.

## Evaluation: LLM judges, deterministic joins

Per video, judgment is cheap text-only work (~5 calls) on top of the two
expensive video calls:

```
judge(description) judge(audio) judge(visual)   one evidence source per call
matcher                                          sub-steps ↔ observed actions
```

Code then does everything trust-critical:

- assigns every ID (steps `s1`, sub-steps `s1a`, claims `c1`, facts, actions)
  and validates every reference an LLM makes;
- joins per-source verdicts by claimId: `SUPPORTED` + `CONTRADICTED` across
  sources → `CONFLICT (source끼리 충돌)` — a model shown all sources at once
  would harmonize them, so no model ever sees more than one;
- validates matches (continuity, sharing, two-level ordering) and rolls
  sub-step results up to steps;
- computes temporal IoU between claimed step spans and observed action spans
  (integer ms, half-open intervals);
- records every anomaly as a validation issue instead of silently fixing it.

There is deliberately **no composite quality score**: contradictions, order
conflicts, and unverified segments are different failure modes and must stay
visible separately.

## Failure handling for LLM output

| Response state | Handling |
|---|---|
| Parse failure, unknown IDs, duplicate IDs | Retry the full batch (no partial merges) |
| Valid but some IDs missing | Re-request only the missing IDs (item verdicts are independent) |
| Context overflow | Explicit `INPUT_TOO_LARGE` failure, no retry |

Every attempt is recorded with model ID, prompt version/hash, and token usage.

## Artifacts and provenance

One run writes `candidate`, `blind`, `description-facts`, `evaluation`,
`manifest`, and (when the gate ran) `domain-check` to `output/<videoId>/`.
`SCHEMA_VERSION` (`models/base.py`) versions the JSON contract. The manifest
lists every LLM call; the `ANALYZED` quality event (`events.py`) is appended as
an immutable file per event. The event types beyond `ANALYZED` — `REVISED`,
`APPROVED`, `REJECTED`, `PUBLISHED` — exist so a review layer built on top can
log its decisions in the same stream and later join what evaluation missed
against what humans fixed.

## Domain boundary

The recipe domain lives in three places: the candidate schema
(`models/candidate.py`), the prompts (`extraction/prompts/*.md`, versioned),
and the claim and omission rules (`evaluation/claims.py`,
`evaluation/omissions.py`). ID assignment, per-source judging, verdict joins,
sub-step matching, temporal IoU, and validation are domain-agnostic. Adapting
unbake to another procedural domain means replacing the first group, not the
second.
