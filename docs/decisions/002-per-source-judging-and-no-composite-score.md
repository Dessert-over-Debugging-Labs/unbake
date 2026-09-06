# 002. One evidence source per judge call; no composite quality score

- Date: 2026-09-05
- Status: accepted
- Decided by: human

## Decision
Each judging call sees exactly one evidence source (description, audio, or
visual) with all claims. Cross-source conflicts are found by a deterministic
join on claimId. No single 0–100 quality score is ever produced.

## Rationale
A judge shown all sources at once harmonizes them and buries conflicts —
observed in practice (an on-screen caption and the narration disagreeing on an
amount surfaces as `CONFLICT` only because the judges could not see each other).
A composite score lets unrelated error kinds average each other out.

## Links
—
