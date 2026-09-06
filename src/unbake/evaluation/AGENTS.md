# evaluation/

Deterministic verification core. **No LLM calls from this package** — judges and
matchers come in through ports. Decision tables (fuse, severity, rollup) are
golden-tested: change a table and its test together. Time is integer
milliseconds, half-open `[startMs, endMs)`.
