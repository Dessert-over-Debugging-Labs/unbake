# Architecture

unbake extracts a structured recipe from a cooking video, then **verifies it**
by cross-checking independent extractions with deterministic code. The design
premise: a model's self-reported confidence is not evidence. Verification comes
from independence and joins, not from asking the extractor how sure it is.

## Pipeline

```
discover → filter → gate → extract → evaluate → structure → review (human) → publish
```

- **discover/filter** — find candidate videos (YouTube Data API, quota-aware),
  drop non-recipe content, and honor channels whose descriptions forbid reuse.
- **gate** — immediately before any video is sent to a model, a text-only judge
  reads the title, channel, and description and decides whether this is a
  cooking video at all. It runs on every path (batch and single-URL
  evaluation), on a cheap OpenRouter model by default or on Gemini. Off-domain
  videos become `filtered_out` with the verdict recorded; a judge failure is a
  recorded failure, never a silent pass. The threshold lives in code, not in
  the prompt.
- **extract** — three independent LLM extractions per video (see below).
- **evaluate** — deterministic cross-validation producing per-claim verdicts,
  step matching, and temporal metrics.
- **structure** — map the intermediate representation to the target backend DTO;
  deterministic normalization (units, boundary padding) applies only to this
  mapped copy, never to the original candidate.
- **review** — a human approves, edits (as new revisions), or rejects. Only
  approved revisions can be published; production publishing is a human button.

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

## State and provenance

Two layers track progress: a workflow state machine
(`queued → analyzing → evaluating → pending_review → …`, explicit transition
table; the domain gate may also send `queued → filtered_out`) and per-run
evaluation records (attempt, input hash, artifact path).
Human edits never overwrite: they append revisions, and publishing always
references an approved revision. Every significant action (analysis, revision,
approval, rejection, publishing) is appended as an immutable quality event —
the raw material for measuring what evaluation missed and humans fixed.
