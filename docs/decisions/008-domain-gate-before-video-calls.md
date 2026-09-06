# 008. Domain gate before any video call; OpenRouter as its default text provider

- Date: 2026-09-06
- Status: accepted
- Decided by: human (on agent proposal)

## Decision
Every path that would send a video to a model — batch and single-URL evaluation
alike — first runs a cheap, text-only "is this a cooking video?" judge on the
title, channel, and description. It defaults to an OpenRouter model
(`OPENROUTER_API_KEY`), can reuse Gemini (`DOMAIN_CHECK=gemini`), or be turned
off. Off-domain videos are recorded as `filtered_out` with the verdict; a judge
failure is a recorded failure, never a pass. The confidence threshold lives in
code, not in the prompt.

## Rationale
The batch filter's recipe check only covers discovered candidates; hand-fed
URLs and previously queued videos reached the two expensive video calls
unchecked. A metadata judge needs no video input and costs a fraction of a
cent, so a second provider with cheap text models fits — and keeping the judge
behind a `generate_json` interface means the Gemini client works too, so nobody
is forced onto OpenRouter. Rejected: extending only the Gemini filter judge
(still skips the single-URL path), and failing open on judge errors (would
silently disable the gate).

## Links
—
