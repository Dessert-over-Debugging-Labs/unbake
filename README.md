# unbake

Extract structured recipes from YouTube cooking videos — ingredients, amounts,
steps, and per-step timestamps. Every claim is cross-checked against the video.
No downloads, just a URL.

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

Key properties:

- **IDs are assigned by code**, never by a model; every model reference is validated.
- **The blind observer can't cheat** — its function signature accepts only a video URL.
- **No composite score.** Contradictions, order conflicts, and unverified
  segments stay visible as separate counts.
- **Nothing is published without human approval.** Edits are append-only
  revisions; production publishing is a human button in the review dashboard.

## Pipeline

```
discover → filter → gate → extract → evaluate → structure → review (human) → publish
```

Discovery uses the YouTube Data API (quota-aware, two-track search + channel
backfill). The filter drops non-recipe content and honors channels whose
descriptions forbid reuse (they are recorded, with evidence, and skipped until
consent). The **domain gate** is a cheap, text-only "is this a cooking video?"
judge that runs right before any video call — on every path, including a URL
you pass by hand — so off-topic videos never reach the expensive extraction.
See [docs/architecture.md](docs/architecture.md) for the full design.

## Quickstart

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env          # GEMINI_API_KEY · YOUTUBE_API_KEY (discovery) · OPENROUTER_API_KEY (gate)
.venv/bin/pytest              # 240 tests, no network

unbake evaluate <youtube-url>   # analyze + cross-validate one video → output/<videoId>/
unbake batch --count 3          # discover → filter → analyze a small batch
python -m unbake.review         # review dashboard → http://localhost:5180
```

Discovery (`unbake batch`) reads its dish list and channel whitelist from
`seeds/dishes.json` and `seeds/channels.json`. Those files are yours and
git-ignored; until you create them, the bundled `seeds/*.example.json`
templates are used. Channels whose descriptions restrict reuse are recorded in
`seeds/consent-required-channels.json` and skipped until consent is granted.

The domain gate runs on an OpenRouter model by default (set `OPENROUTER_API_KEY`;
without it the gate is off). `DOMAIN_CHECK=gemini` reuses your Gemini key
instead, `DOMAIN_CHECK=off` disables it, and `--skip-domain-check` bypasses it
for one run. Every verdict is saved as `output/<videoId>/domain-check.json`.

Model IDs are configured per role (generator / blind observer / description /
judge / matcher / domain gate) in `src/unbake/config.py` and can be overridden
with `GEMINI_MODEL_*` and `DOMAIN_MODEL` environment variables — exact IDs only,
no `latest` aliases.

## Layout

```
src/unbake/
├── models/       # serialization contracts (candidate IR, facts, evaluation)
├── evaluation/   # deterministic verification core (no LLM calls)
├── extraction/   # versioned prompts + extraction ports
├── filtering/    # candidate filtering, reuse-restriction detection
├── adapters/     # gemini · openrouter · youtube · sqlite · naembii (example publish target)
├── workflow/     # orchestration (analyze, batch) over an explicit state machine
└── review/       # human review server; dashboard/ is the vanilla-JS UI
```

`adapters/naembii/` is a working publish adapter for a production recipe
service — kept as a realistic example of the mapping layer. Extraction and
evaluation run fully without it. To connect your own backend, see
[docs/adapters.md](docs/adapters.md) — or let a coding agent assemble the
adapter for you with the `build-publish-adapter` skill.

## Beyond recipes

The pipeline ships focused on cooking videos — the schema, prompts, and filter
are unapologetically about food. The verification approach underneath (dual
independent extraction, per-claim verdicts with one evidence source per judge,
deterministic joins, temporal IoU) applies to any procedural video; adapting it
means rewriting the prompts and the domain schema, not the verification core.

## License

MIT — see [LICENSE](LICENSE). Independently of the license, the filter treats
creator consent as a first-class signal: channels that forbid reuse in their
descriptions are detected and excluded.
