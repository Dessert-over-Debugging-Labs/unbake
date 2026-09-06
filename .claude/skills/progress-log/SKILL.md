---
name: progress-log
description: Write a session handoff entry in notes/progress/ (local-only, git-excluded) — one file per date and PR — and refresh the rolling status in notes/progress/README.md. Use at the end of a working session, after a PR is opened or merged, or whenever the next session would otherwise have to rediscover context.
---

# Recording progress

`notes/` is local-only (`.git/info/exclude`) and may not exist in this checkout.
Never `git add` anything under it. If the folder is missing, ask before creating
it — it is the operator's private working memory, not project documentation.

## 1. One entry per session or PR

File: `notes/progress/YYYY-MM-DD-<slug>.md`. When the work has a pull request,
name it `YYYY-MM-DD-pr<N>-<slug>.md` so entries sort by date and group by PR.
Several entries on one day are fine. Past entries are append-only — the only
edit allowed later is filling in a PR or commit link that did not exist yet.

Template:

```markdown
# YYYY-MM-DD — <one-line title>

- PR: #N (<url>) | —
- Commits: <first>..<last> on <branch> | 미커밋
- Decisions: docs/decisions/NNN | —

## 한 일
(what changed, in the order it happened; name files only when the reader must go there)

## 근거·판단
(why it was done this way; anything a future reader would question)

## 남은 일
(concrete next steps, most urgent first)

## 주의
(traps discovered: quotas, flaky models, things that must never be pushed)
```

## 2. Refresh the rolling status

`notes/progress/README.md` holds only what is true *now*: current state, the
document-placement rules, the prioritized backlog, and standing cautions. Move
history out of it into entries; keep it short enough to read in one screen.

## 3. Style

Korean, like the existing notes; absolute dates (2026-09-06, never "today");
do not duplicate decision records — link them. Do not mention open-source
release preparation in anything that ends up in the public repo.
