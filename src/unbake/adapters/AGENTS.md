# adapters/

External system integrations and DTO mapping. Dependencies point inward:
`models/` and `evaluation/` must not import from concrete adapters. `naembii/`
is a working example of a publish target — extraction and evaluation run fully
without its configuration.

Building a new publish adapter? Follow `docs/adapters.md` (contract) and the
`build-publish-adapter` skill; validate with `tests/adapters/publisher_contract.py`.
