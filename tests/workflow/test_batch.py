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
