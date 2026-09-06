# 007. Seed lists are operator-local; the repo ships templates only

- Date: 2026-09-06
- Status: superseded by 009
- Decided by: human (on agent proposal)

## Decision
The discovery seed lists (`seeds/dishes.json`, `seeds/channels.json`) and the
consent registry (`seeds/consent-required-channels.json`) are operator-local
and git-ignored. The repository ships `seeds/*.example.json` templates, and
discovery falls back to a template when the real file is absent. The seed
files were also removed from the published history.

## Rationale
The lists are operational data, not part of the tool: which channels we
collect from, which channels asked not to be reused (with quoted evidence),
and the notes behind those calls. Publishing them exposes per-channel
judgments and makes every operator inherit ours. Committing them as defaults
was rejected for that reason; deleting them outright was rejected because
discovery reads them at runtime and a fresh clone would fail.

## Links
—
