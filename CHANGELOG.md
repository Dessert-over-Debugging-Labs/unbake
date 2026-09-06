# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/) — `SCHEMA_VERSION` in `models/base.py` versions
the artifact JSON separately.

## [0.1.1] - 2026-09-06

### Added
- `Config` and `ModelConfig` are exported from the package root, so keys and
  model IDs can be passed in code: `make_recipe(url, config=Config(...))`.

### Changed
- Repository tooling: pre-commit (ruff + whitespace/EOF/yaml/toml), Dependabot,
  branch protection on `main`. The custom commit-message hook is gone.

## [0.1.0] - 2026-09-06

First tagged release. The library ends at the artifacts: `make_recipe(url)`
runs gate → extract → evaluate and returns (and writes) the artifact set.
Earlier, untagged history also carried a discovery/review/publishing
pipeline; that layer now lives outside this package (decision 009).

### Added
- `make_recipe(url)` — one-call library entry point; assembles default Gemini
  ports, runs the gate and the pipeline, writes the artifact set.
- Domain gate: a text-only "is this a cooking video?" judge before any video
  call (OpenRouter by default, Gemini optional, off without a key). Verdicts
  are saved as `domain-check.json`; a rejected video raises `OffDomainError`.
- `unbake <url>` CLI (single command), `--version`, `-o/--output`.
- GitHub Actions CI (ruff + pytest on 3.11–3.13).

### Notes
- Saved and returned artifacts now carry the code-assigned IDs (`s1`, `s1a`,
  `i1`, `a1`, `d1`), so evaluation references resolve against the files alone.
- The library now ends at the artifacts (decision 009). Discovery, batch
  filtering, the SQLite state machine, the review dashboard and server, and the
  publish adapter kit were removed from this repository.
- `Config.load()` reads `.env` from the current working directory (not the
  package root) and honors `UNBAKE_OUTPUT_DIR`.
- `workflow/analyze.py` → `pipeline.py`; `filtering/domain.py` + `workflow/gate.py`
  → `gate.py`.
