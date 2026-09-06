# 006. Publish adapters: neutral contract + assembly kit, naembii as reference

- Date: 2026-09-06
- Status: proposed
- Decided by: — (agent proposal, awaiting human confirmation)

## Decision
Keep the naembii adapter as the working reference implementation, and make
"bring your own backend" a supported path: a neutral publishing contract
(`unbake/publishing.py` — PublishResult, Publisher, StructureOutcome; mapper
injectable into ReviewService), a guide (`docs/adapters.md`), repo-managed
contract test helpers, and an agent skill (`build-publish-adapter`) that
interviews the user and assembles a new adapter.

## Rationale
A bare example alone makes users reverse-engineer the contract; removing the
example would trade a real, production-tested integration for a toy. The kit
gives both: the example stays honest (its policies are labeled backend-specific,
e.g. 409-as-duplicate-success), and the contract plus shared tests keep
generated adapters from encoding one author's misconception.

## Links
—
