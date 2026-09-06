# 004. Human approval gate; edits are append-only revisions

- Date: 2026-09-05
- Status: accepted
- Decided by: human

## Decision
Nothing is published without human approval, and production publishing happens
only through an explicit human action in the review dashboard. Human edits never
overwrite the extracted candidate — they create new revisions, and publishing
references an approved revision.

## Rationale
Automated evaluation flags problems; it does not decide releases. Preserving
the original candidate next to human corrections is what later lets us measure
what evaluation missed (via immutable quality events joining the two).

## Links
—
