"""배치 오케스트레이션 — 상태 2층(workflow + run) 추적 검증."""

import pytest

from tests.evaluation.conftest import FakeJudge, FakeMatcher, make_candidate
from unbake.adapters.sqlite import store as S
from unbake.adapters.sqlite.store import Store
from unbake.evaluation.recovery import LlmParseError
from unbake.events import list_events
from unbake.models import LlmCallRecord
from unbake.workflow.batch import AnalysisPorts, analyze_queued

VID = "abc123def45"


def _rec(purpose: str) -> LlmCallRecord:
    return LlmCallRecord(
        call_id=f"{purpose}-1", purpose=purpose, model="fake",
        prompt_version="t", prompt_hash="h",
    )


class FakeGenerator:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def extract_candidate(self, video_url, video_id, duration_ms, description):
        if self.error:
            raise self.error
        candidate = make_candidate(
            [("절이기", (0, 20_000), ["애호박을 채 썬다"])], ingredients=[("애호박", "1개")]
        ).model_copy(update={"video_id": video_id, "duration_ms": duration_ms})
        return candidate, _rec("extract_a")


class FakeBlind:
    def extract_facts(self, video_url, duration_ms):
        from unbake.models import BlindExtraction, VideoAction

        blind = BlindExtraction(
            actions=[VideoAction(description="채 썬다", start_ms=0, end_ms=18_000)]
        )
        return blind, _rec("extract_b")


class FakeDescParser:
    def parse(self, description):
        from unbake.models import DescriptionFacts

        return DescriptionFacts(), _rec("parse_description")


class BrokenJudge:
    def judge(self, claims, facts, requested_claim_ids):
        raise LlmParseError("항상 깨짐")


def _ports(generator=None, judge=None) -> AnalysisPorts:
    return AnalysisPorts(
        generator=generator or FakeGenerator(),
        blind_extractor=FakeBlind(),
        description_parser=FakeDescParser(),
        judge=judge or FakeJudge(),
        matcher=FakeMatcher({"s1a": ("MATCHED", ["a1"])}),
    )


@pytest.fixture
def queued_store(tmp_path):
    db_path = tmp_path / "pipeline.db"
    store = Store(db_path)
    store.discover(VID, title="애호박볶음", channel_title="채널A", duration_ms=60_000)
    store.transition(VID, S.QUEUED)
    yield store, tmp_path / "output"
    store.close()


def _meta(_vid):
    return {"durationMs": 60_000, "description": "애호박 1개", "title": "t", "channelTitle": "c"}


def test_성공_경로_상태_2층_추적(queued_store):
    store, output_dir = queued_store
    report = analyze_queued(
        store=store, output_dir=output_dir, ports=_ports(), meta_fetcher=_meta, count=3
    )

    assert report.analyzed == [VID] and report.failed == []
    assert store.get(VID)["state"] == S.PENDING_REVIEW

    runs = store.list_runs(video_id=VID)
    assert len(runs) == 1
    assert runs[0]["status"] == S.RUN_SUCCEEDED
    assert runs[0]["artifact_path"] == f"{VID}/evaluation.json"
    assert runs[0]["input_hash"]

    assert store.get_revision(f"rev-{VID}-orig") is not None
    assert (output_dir / VID / "evaluation.json").exists()
    assert (output_dir / VID / "meta.json").exists()
    assert any(e["eventType"] == "ANALYZED" for e in list_events(output_dir, video_id=VID))


def test_추출_실패는_analyze_failed_run_없음(queued_store):
    store, output_dir = queued_store
    report = analyze_queued(
        store=store, output_dir=output_dir,
        ports=_ports(generator=FakeGenerator(error=RuntimeError("영상 접근 불가"))),
        meta_fetcher=_meta, count=3,
    )
    assert report.analyzed == []
    assert store.get(VID)["state"] == S.ANALYZE_FAILED
    assert "영상 접근 불가" in store.get(VID)["reason"]
    assert store.list_runs(video_id=VID) == []


def test_평가_실패는_evaluation_failed_run_failed(queued_store):
    store, output_dir = queued_store
    report = analyze_queued(
        store=store, output_dir=output_dir, ports=_ports(judge=BrokenJudge()),
        meta_fetcher=_meta, count=3,
    )
    assert report.analyzed == []
    assert store.get(VID)["state"] == S.EVALUATION_FAILED
    runs = store.list_runs(video_id=VID)
    assert len(runs) == 1 and runs[0]["status"] == S.RUN_FAILED
    # 추출 산출물(candidate)은 남아 있어 재평가 재시도가 가능하다
    assert (output_dir / VID / "candidate.json").exists()


def test_한_건_실패가_배치를_죽이지_않는다(queued_store):
    store, output_dir = queued_store
    vid2 = "zzz999zzz99"
    store.discover(vid2, title="김치찌개", channel_title="채널B", duration_ms=60_000)
    store.transition(vid2, S.QUEUED)

    calls = {"n": 0}

    class FlakyGenerator(FakeGenerator):
        def extract_candidate(self, video_url, video_id, duration_ms, description):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("첫 건만 실패")
            return super().extract_candidate(video_url, video_id, duration_ms, description)

    report = analyze_queued(
        store=store, output_dir=output_dir, ports=_ports(generator=FlakyGenerator()),
        meta_fetcher=_meta, count=3,
    )
    assert len(report.failed) == 1
    assert len(report.analyzed) == 1


# ── 요리 도메인 게이트 — 영상 호출 전에 메타만으로 거른다 (decision 008) ──

class FakeDomainJudge:
    def __init__(self, is_cooking=True, confidence=0.9, error=None):
        from unbake.filtering.domain import DomainVerdict

        self.verdict = DomainVerdict(is_cooking=is_cooking, confidence=confidence,
                                     reason="테스트", model="fake", prompt_version="0",
                                     prompt_hash="h")
        self.error, self.calls = error, 0

    def judge(self, video_block):
        self.calls += 1
        if self.error:
            raise self.error
        return self.verdict


class CountingGenerator(FakeGenerator):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def extract_candidate(self, *a, **k):
        self.calls += 1
        return super().extract_candidate(*a, **k)


def test_도메인_탈락은_filtered_out_이고_영상_호출이_없다(queued_store):
    store, output_dir = queued_store
    generator = CountingGenerator()
    report = analyze_queued(
        store=store, output_dir=output_dir, ports=_ports(generator=generator),
        meta_fetcher=_meta, count=3, domain_judge=FakeDomainJudge(is_cooking=False),
    )
    assert report.off_domain == [(VID, "off_domain: 테스트")]
    assert report.analyzed == [] and report.failed == []
    assert store.get(VID)["state"] == S.FILTERED_OUT
    assert store.get(VID)["reason"] == "off_domain: 테스트"
    assert generator.calls == 0
    assert store.list_runs(video_id=VID) == []
    # 판정은 산출물로 남고, candidate.json 이 없으니 검수 목록에는 안 잡힌다
    assert (output_dir / VID / "domain-check.json").exists()
    assert not (output_dir / VID / "candidate.json").exists()


def test_도메인_통과는_평소처럼_분석하고_판정_산출물을_남긴다(queued_store):
    import json

    store, output_dir = queued_store
    judge = FakeDomainJudge(is_cooking=True, confidence=0.9)
    report = analyze_queued(
        store=store, output_dir=output_dir, ports=_ports(), meta_fetcher=_meta, count=3,
        domain_judge=judge,
    )
    assert report.analyzed == [VID] and report.off_domain == []
    assert judge.calls == 1
    check = json.loads((output_dir / VID / "domain-check.json").read_text(encoding="utf-8"))
    assert check["passed"] is True and check["verdict"]["model"] == "fake"
    assert "도메인 탈락 0건" in report.summary_line()


def test_도메인_판정_실패는_통과가_아니라_analyze_failed(queued_store):
    store, output_dir = queued_store
    generator = CountingGenerator()
    report = analyze_queued(
        store=store, output_dir=output_dir, ports=_ports(generator=generator),
        meta_fetcher=_meta, count=3,
        domain_judge=FakeDomainJudge(error=RuntimeError("openrouter 503")),
    )
    assert report.analyzed == [] and report.off_domain == []
    assert len(report.failed) == 1 and "domain_check_error" in report.failed[0][1]
    assert store.get(VID)["state"] == S.ANALYZE_FAILED
    assert generator.calls == 0


def test_게이트가_없으면_기존과_동일(queued_store):
    store, output_dir = queued_store
    report = analyze_queued(
        store=store, output_dir=output_dir, ports=_ports(), meta_fetcher=_meta, count=3,
    )
    assert report.analyzed == [VID]
    assert not (output_dir / VID / "domain-check.json").exists()
