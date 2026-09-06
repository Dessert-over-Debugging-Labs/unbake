# 003. Analyze videos from their URL; no downloads

- Date: 2026-09-05
- Status: accepted
- Decided by: human

## Decision
Videos are analyzed by passing their URL directly to the model's video input.
The pipeline never downloads video files, and no download fallback is added.

## Rationale
Direct URL analysis is faster, needs no storage, reads on-screen captions that
transcript-only approaches structurally miss (amounts are often shown, not
spoken), and avoids the terms-of-service gray zone of downloading platform
content. Measured on real videos before adoption.

## Links
—
