# 005. Model IDs: single source of truth, per-role, exact pins

- Date: 2026-09-05
- Status: accepted
- Decided by: human

## Decision
Model IDs appear in exactly one place (`config.DEFAULT_MODELS`), one entry per
role (generator, blind, description, judge, matcher), each overridable via
`GEMINI_MODEL_*` environment variables. Exact model IDs only — no `latest`
aliases. Adapters take the model as a required constructor argument.

## Rationale
Provenance and reproducibility require knowing exactly which model produced an
artifact. Per-role configuration lets the judge be swapped independently of the
extractors (e.g., for correlation experiments) without touching code.

## Links
—
