# unbake

YouTube cooking video in, cross-verified structured recipe out — ingredients,
amounts, steps, sub-steps, and per-step timestamps. Every claim is checked
against the video itself. No downloads, just a URL.

```python
from unbake import make_recipe

artifacts = make_recipe("https://www.youtube.com/watch?v=U9MF9r1lLTg")
artifacts.candidate.ingredients     # [CandidateIngredient(name='치즈', amount='1컵', ...), ...]
artifacts.candidate.steps           # [CandidateStep(step_id='s1', title='...', start_ms=..., ...)]
artifacts.evaluation.summary        # contradictions, source conflicts, temporal IoU, ...
```

```bash
unbake https://www.youtube.com/watch?v=U9MF9r1lLTg   # same thing from the shell → ./output/<videoId>/
```

## Why another recipe extractor?

Transcript-based tools can't see the screen — and cooking videos put the
numbers on the screen. In one measured test video, **0 of 21 ingredient amounts
were spoken aloud**; every amount appeared only as an on-screen caption.

unbake analyzes the video itself (frames, audio, and on-screen text) via
Gemini's direct video-URL input, and then refuses to take the extraction on
faith:

```
Generator A        video + description → recipe candidate (steps, sub-steps, timestamps)
Blind observer B   video only          → observed facts + timed cooking actions
Description parser description only    → description facts
        ↓
Judges (one evidence source per call)   claim ↔ facts verdicts
        ↓
Deterministic code                      ID assignment · verdict joins · CONFLICT
                                        detection · step matching · temporal IoU
        ↓
Recipe candidate + evaluation report    what's supported, what's contradicted,
                                        which segments look wrong
```

Real example: an on-screen caption said *"1 spoon of oil"* while the narration
said *"just a drizzle"*. Because the audio judge and the visual judge can't see
each other, the disagreement survives to the report as a `CONFLICT` for a human
to settle — instead of a model quietly picking one.

- **IDs are assigned by code**, never by a model; every model reference is validated.
- **The blind observer can't cheat** — its function signature accepts only a video URL.
- **No composite score.** Contradictions, order conflicts, and unverified
  segments stay visible as separate counts.
- **Nothing is silently fixed.** Invalid model output becomes a recorded
  validation issue, and every call is logged with model ID, prompt version, and
  token usage.

## Install

```bash
pip install git+https://github.com/Dessert-over-Debugging-Labs/unbake        # latest main
pip install "unbake @ git+https://github.com/Dessert-over-Debugging-Labs/unbake@v0.2.0"
```

Python 3.11+. Two runtime dependencies (`pydantic`, `requests`).

Put keys in the environment or a `.env` in your working directory
(see [.env.example](.env.example)):

| Variable | Needed for |
|---|---|
| `GEMINI_API_KEY` | extraction and judging — required |
| `YOUTUBE_API_KEY` | fetching title/description/duration for a URL — optional if you pass `description` yourself |
| `OPENROUTER_API_KEY` | the domain gate below — optional; without it the gate is off |

## What you get

`make_recipe()` returns an `AnalysisArtifacts` and, by default, writes the same
six files to `output/<videoId>/`:

| File | Contents |
|---|---|
| `candidate.json` | the recipe: ingredients with amounts, steps with `[startMs, endMs)` spans, sub-steps — each with the code-assigned ID (`i1`, `s1`, `s1a`) that `evaluation.json` refers to |
| `blind.json` | what the blind observer saw: audio facts, visual facts, timed actions |
| `description-facts.json` | facts parsed from the description only |
| `evaluation.json` | per-claim verdicts per source, fused verdicts, step roll-ups, temporal IoU, omissions, validation issues |
| `manifest.json` | every LLM call: model ID, prompt version and hash, tokens, status |
| `domain-check.json` | the gate's verdict, when the gate ran |

All timestamps are integer milliseconds with half-open intervals. The JSON is
camelCase; the Python objects are snake_case pydantic models
(`unbake.models`). `SCHEMA_VERSION` is the contract — pin it downstream.

## Domain gate

Video calls are the expensive part. Before any video is sent to a model, a
cheap text-only judge reads the title, channel, and description and decides
whether this is a cooking video at all. It runs on an OpenRouter model by
default, can reuse your Gemini key (`DOMAIN_CHECK=gemini`), or be turned off
(`DOMAIN_CHECK=off`, or `--skip-domain-check` / `check_domain=False`). A
rejected video raises `OffDomainError` with the verdict; the judge failing is
an error, never a silent pass.

## Bring your own models

Model IDs live in one place, `unbake.config.DEFAULT_MODELS`, one per role
(generator, blind observer, description parser, judge, matcher, domain gate),
each overridable with `GEMINI_MODEL_*` / `DOMAIN_MODEL` — exact IDs only, no
`latest` aliases. To use a different provider entirely, implement the five
ports in `unbake.extraction.ports` and `unbake.evaluation.ports` and call
`unbake.pipeline.analyze_and_evaluate` directly, or pass them to
`make_recipe(..., ports=RecipePorts(...))`.

## What unbake deliberately does not do

The library ends at the artifacts. Finding videos, queueing and batching,
human review, and publishing to a backend are yours to build on top — they
depend on your catalog, your reviewers, and your schema. Two things unbake
does give you for that layer: the artifact schema above, and an append-only
quality-event log (`unbake.events`) whose event types (`ANALYZED`, `REVISED`,
`APPROVED`, `REJECTED`, `PUBLISHED`) are the hooks a review flow needs.

## Layout

```
src/unbake/
├── api.py          # make_recipe — assembles default ports, runs the pipeline
├── pipeline.py     # analyze_and_evaluate / save_artifacts (port-based, provider-free)
├── gate.py         # domain gate: verdict, threshold, artifact
├── models/         # pydantic contracts (candidate IR, facts, evaluation, provenance)
├── extraction/     # versioned prompts + extraction ports
├── evaluation/     # deterministic verification core (no LLM calls)
├── adapters/       # gemini (video) · openrouter (text) · youtube (metadata)
├── config.py       # .env loader, model IDs (single source of truth)
└── events.py       # append-only quality events
```

## Beyond recipes

unbake ships focused on cooking videos — the schema, prompts, and gate are
unapologetically about food. The verification approach underneath (dual
independent extraction, per-claim verdicts with one evidence source per judge,
deterministic joins, temporal IoU) applies to any procedural video. The
recipe-specific pieces are the candidate schema (`models/candidate.py`), the
prompts (`extraction/prompts/`), and the claim/omission rules
(`evaluation/claims.py`, `evaluation/omissions.py`); the rest is generic.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Design rationale lives in
[docs/architecture.md](docs/architecture.md) and the decision records in
[docs/decisions/](docs/decisions/).

## License

MIT — see [LICENSE](LICENSE).
