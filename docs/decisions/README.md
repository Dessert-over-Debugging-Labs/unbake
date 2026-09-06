# Decision records

Significant decisions — architecture, data contracts, operational policy,
trade-offs worth remembering — are recorded here so the "why" survives the
conversation it happened in.

Not every commit needs a record. Record a decision when future readers might
reasonably ask "why is it this way?" and the answer isn't obvious from code.

## Format

One file per decision: `NNN-short-slug.md` (three-digit, ascending).

```markdown
# NNN. Title (one line, imperative or noun phrase)

- Date: YYYY-MM-DD
- Status: proposed | accepted | superseded by NNN
- Decided by: human | human (on agent proposal)

## Decision
One or two sentences.

## Rationale
Two or three lines. What was the alternative, and why not.

## Links
Related commits / PRs / records. "—" until they exist.
```

## Rules

- **Agents never mark their own proposal `accepted`** — they file it as
  `proposed`; a human flips the status.
- A superseded record is never deleted — its status changes and it points to
  its successor.
