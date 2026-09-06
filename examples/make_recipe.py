"""Minimal library usage — one video in, verified recipe out.

    GEMINI_API_KEY=... YOUTUBE_API_KEY=... python examples/make_recipe.py <youtube-url>

Set OPENROUTER_API_KEY to enable the domain gate; pass --no-gate to skip it.
"""

import sys

from unbake import OffDomainError, make_recipe


def main(url: str, gate: bool) -> int:
    try:
        artifacts = make_recipe(url, check_domain=None if gate else False)
    except OffDomainError as exc:
        print(f"not a cooking video: {exc.gate.reason}")
        return 2

    c, s = artifacts.candidate, artifacts.evaluation.summary
    print(f"{c.dish_name}: {len(c.ingredients)} ingredients, {len(c.steps)} steps")
    for step in c.steps:
        print(f"  {step.step_id} [{step.start_ms}–{step.end_ms}ms] {step.title}")
    print(
        f"verdicts: {s.contradiction_count} contradictions, "
        f"{s.source_conflict_count} source conflicts, median tIoU {s.median_temporal_iou}"
    )
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(main(args[0], gate="--no-gate" not in sys.argv))
