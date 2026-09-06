# adapters/

External system boundaries. Dependencies point inward: `models/`, `evaluation/`,
`pipeline.py`, and `gate.py` must not import from concrete adapters.

- `gemini/` — the only adapter that takes video input (URL attached directly,
  no download). Implements all five extraction/evaluation ports.
- `openrouter/` — text-only (no video input), for cheap judgments — today the
  cooking-domain gate. Its judge is written against a `generate_json`
  interface, so the Gemini client can stand in (`DOMAIN_CHECK=gemini`); keep
  new text-only judges provider-neutral the same way.
- `youtube/` — Data API metadata lookup (title, description, duration). Optional:
  callers may pass description and duration themselves.

Adding a provider: implement the ports in `extraction/ports.py` and
`evaluation/ports.py`, return `LlmCallRecord`s with exact model IDs, and raise
`LlmParseError` / `InputTooLargeError` from `evaluation/recovery.py` so the
retry policy applies.
