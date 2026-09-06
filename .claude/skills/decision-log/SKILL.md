---
name: decision-log
description: Record a significant project decision (architecture, data contract, operational policy, notable trade-off) as a file in docs/decisions/. Use when such a decision is made or proposed during a session — so the "why" is not lost when the conversation ends.
---

# Recording a decision

1. Decide whether it qualifies: would a future reader ask "why is it this way?"
   and not find the answer in code? Routine implementation choices do not
   qualify — do not log per-commit noise.
2. Read `docs/decisions/README.md` and take the next number `NNN`.
3. Create `docs/decisions/NNN-short-slug.md` following the template there:
   Date / Status / Decided by / Decision (1–2 sentences) / Rationale (2–3
   lines, including the rejected alternative) / Links.
4. Status rules — strict:
   - If a **human** made or confirmed the decision in the session: `accepted`,
     `Decided by: human` (or `human (on agent proposal)`).
   - If **you** are proposing it: `proposed`. **Never mark your own proposal
     `accepted`** — tell the user it awaits their confirmation.
5. Add commit/PR links once they exist; `—` until then.
6. When a new decision replaces an old one, set the old record's status to
   `superseded by NNN` — never delete it.
