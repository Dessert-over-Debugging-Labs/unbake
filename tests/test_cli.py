"""CLI — 단일 명령 파싱, 종료 코드, make_recipe 로의 위임."""
from unbake import cli
from unbake.api import OffDomainError
from unbake.gate import DomainVerdict, GateResult


def test_기본_인자_파싱():
    args = cli.build_parser().parse_args(["https://youtu.be/abc123def45", "-o", "here"])
    assert args.url == "https://youtu.be/abc123def45"
    assert args.output == "here" and not args.skip_domain_check


def test_게이트_탈락은_exit_2(monkeypatch):
    def rejecting(*a, **k):
        verdict = DomainVerdict(is_cooking=False, confidence=0.05, reason="뮤직비디오")
        raise OffDomainError(GateResult(False, "off_domain: 뮤직비디오", verdict))

    monkeypatch.setattr(cli, "make_recipe", rejecting)
    assert cli.main(["abc123def45"]) == 2


def test_입력_오류는_exit_1(monkeypatch):
    def failing(*a, **k):
        raise ValueError("유튜브 URL 을 해석하지 못했습니다")

    monkeypatch.setattr(cli, "make_recipe", failing)
    assert cli.main(["nope"]) == 1


def test_skip_플래그는_check_domain_False로_전달(monkeypatch):
    from types import SimpleNamespace as NS

    seen = {}
    summary = NS(contradiction_count=0, source_conflict_count=0, unknown_claim_count=0,
                 matched_step_count=0, partial_step_count=0, unmatched_step_count=0,
                 order_conflict_count=0, suspect_segment_count=0, unverified_segment_count=0,
                 median_temporal_iou=None, omission_count=0)
    artifacts = NS(evaluation=NS(summary=summary, claim_evaluations=[], step_rollups=[]))

    def capturing(url, **kwargs):
        seen.update(kwargs)
        return artifacts

    monkeypatch.setattr(cli, "make_recipe", capturing)
    rc = cli.main(["abc123def45", "--skip-domain-check", "--description", "d", "--duration-ms", "5"])
    assert rc == 0
    assert seen["check_domain"] is False and seen["description"] == "d" and seen["duration_ms"] == 5
