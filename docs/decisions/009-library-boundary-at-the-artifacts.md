# 009. The library ends at the artifacts; discovery, review, and publishing live outside

- Date: 2026-09-06
- Status: accepted
- Decided by: human (on agent proposal)

## Decision
unbake is a library plus a thin CLI: `make_recipe(url)` runs gate → extract →
evaluate and returns (and writes) the artifact set. Video discovery, batch
queueing and its filter, the human review dashboard, and publishing to a
backend are removed from this repository and belong to the application that
imports it. The artifact schema (`SCHEMA_VERSION`) and the quality-event types
remain public as the contract for that layer. The domain gate stays, because
"is this video in the domain" is part of the domain definition.

## Rationale
The operational layer was where every "our taste" decision lived — dashboard
UI, YouTube catalog policy, backend DTOs — and none of it is what someone
installs unbake for. Keeping it public forced a half-open pipeline with one
company's publish adapter in it. Cutting at the artifacts leaves a package
that is installable, runnable end to end from a URL, and honest about its
scope. Rejected: keeping the review server as an optional extra (it carries
the approval policy, which is the application's, not the library's), and
purging the removed code from history (nothing in it was secret).

## Links
Supersedes 004, 006, 007 (their policies move to the consuming application).
