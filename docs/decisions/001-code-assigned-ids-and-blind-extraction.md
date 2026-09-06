# 001. Code-assigned IDs and structurally blind extraction

- Date: 2026-09-05
- Status: accepted
- Decided by: human

## Decision
All identifiers (steps, sub-steps, claims, facts, actions) are assigned by
deterministic code; LLMs may only reference existing IDs. The blind observer
extractor receives nothing but a video reference — enforced by its function
signature, not by prompt wording.

## Rationale
Verification is only as trustworthy as the independence of its inputs. If the
observer can see the generator's output (or the description), agreement stops
being evidence. If models invent IDs, every join downstream becomes unreliable.

## Links
—
