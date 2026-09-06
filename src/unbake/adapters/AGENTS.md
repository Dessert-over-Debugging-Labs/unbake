# adapters/

External system integrations and DTO mapping. Dependencies point inward:
`models/` and `evaluation/` must not import from concrete adapters. `naembii/`
is a working example of a publish target — extraction and evaluation run fully
without its configuration.

`openrouter/` is text-only (no video input) and exists for cheap judgments —
today the cooking-domain gate. Its judge is written against a `generate_json`
interface, so the Gemini client can stand in (`DOMAIN_CHECK=gemini`); keep new
text-only judges provider-neutral the same way.

Building a new publish adapter? Follow `docs/adapters.md` (contract) and the
`build-publish-adapter` skill; validate with `tests/adapters/publisher_contract.py`.
