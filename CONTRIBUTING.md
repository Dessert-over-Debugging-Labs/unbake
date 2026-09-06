# Contributing

Thanks for looking. unbake is small on purpose; the bar for a change is "does
it make `make_recipe()` more correct, more verifiable, or easier to run".

## Setup

```bash
git clone https://github.com/Dessert-over-Debugging-Labs/unbake && cd unbake
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
git config core.hooksPath .githooks       # commit message check
.venv/bin/pytest -q && .venv/bin/ruff check src tests
```

Tests are deterministic and make no network calls — fake the clients, not the
ports. A real run needs keys in `.env` (see `.env.example`).

## Ground rules

Read [AGENTS.md](AGENTS.md) first — it lists five architecture invariants
(code-assigned IDs, blind extractor, one evidence source per judge, no
composite score, no silent fixes). A change that touches one of them needs a
decision record in `docs/decisions/` and a human to accept it.

- Conventional Commits, English subjects, ≤72 chars.
- Prompts are versioned: bump the `<!-- version: x.y.z -->` header when you
  change one; the hash is recorded in every manifest.
- Model IDs live only in `config.DEFAULT_MODELS` — exact IDs, no `latest`.
- New providers implement the ports in `extraction/ports.py` and
  `evaluation/ports.py`; see `adapters/AGENTS.md`.

## Reporting a bad extraction

Open an issue with the video URL, the `manifest.json` (model IDs and prompt
versions), and the part of `evaluation.json` that looks wrong. If the video is
not a cooking video, say so — that is a gate bug, not an extraction bug.
