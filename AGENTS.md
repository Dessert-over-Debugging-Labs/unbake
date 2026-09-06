# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.

## What this project is

**unbake** turns YouTube cooking videos into structured, verified recipes —
ingredients, amounts, steps, and per-step video timestamps. The underlying goal:
**video → structured, verified procedure**. Semantic extraction and judgment are
LLM work; combining judgments, validating references, and computing metrics is
deterministic code. Keep that boundary.

## Architecture invariants

Do not break these without a recorded human decision (`docs/decisions/`):

1. **IDs are assigned by code** (stepId, claimId, factId, actionId) — never by an LLM.
2. **The blind extractor sees only the video.** No candidate, no description.
   Its function signature enforces this; keep it that way.
3. **Judges see exactly one evidence source per call.** Cross-source conflicts
   are found by deterministic joins on claimId, not by a model.
4. **No single 0–100 quality score.** Different error kinds must not average out.
5. **Never silently fix invalid data** — record a validation issue instead.

## Conventions

- **Commits**: Conventional Commits (`feat|fix|docs|refactor|test|chore|build|ci|perf|revert`),
  subject in English by default, ≤72 chars. Validated by `.githooks/commit-msg`
  (run `git config core.hooksPath .githooks` once after clone).
- **PRs and issues**: English by default.
- **Decisions**: significant decisions (architecture, contracts, policy trade-offs)
  are recorded in `docs/decisions/`. Agents may add `proposed` records but must
  never mark their own proposal `accepted` — a human does that.
- Run the relevant tests and `ruff check` before committing.
- Secrets live in `.env` (never committed). Model IDs have a single source of
  truth in `src/unbake/config.py` (`DEFAULT_MODELS`), overridable via `GEMINI_MODEL_*`.

## Layout

- `src/unbake/` — the package. Folders with their own AGENTS.md carry local rules.
- `dashboard/` — review UI (vanilla JS, no build step).
- `docs/` — architecture overview and decision records.
- `tests/` — pytest; deterministic, no network calls.
