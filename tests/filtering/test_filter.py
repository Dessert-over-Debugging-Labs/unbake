"""② 5단 필터 — 하드/규칙 컷, 주입된 judge 판별, 스코어링·상태 전이.

기존 저장소에는 필터 전용 테스트가 없었다(하드 필터는 test_licensing에서 간접 검증).
이식하며 judge·history 주입으로 바뀐 계약을 여기서 직접 검증한다.
"""
import pytest

from unbake.adapters.youtube.discover import Candidate
from unbake.filtering import filter as F
from unbake.filtering import licensing as L


@pytest.fixture(autouse=True)
def registry(tmp_path, monkeypatch):
    """이용 제한 등록부를 tmp로 격리 — 테스트가 실제 seeds/를 건드리지 않게."""
    monkeypatch.setattr(L, "REGISTRY", tmp_path / "consent-required-channels.json")
    monkeypatch.setattr(L, "SEEDS_DIR", tmp_path)


def cand(vid="v1", **kw):
    kw.setdefault("title", "김치찌개 레시피")
    kw.setdefault("channel_title", "테스트채널")
    kw.setdefault("duration_ms", 300_000)
    return Candidate(video_id=vid, **kw)


class FakeHistory:
    """duck-typed history — transition 호출을 기록한다."""

    def __init__(self):
        self.transitions = {}

    def transition(self, video_id, new_state, *, reason=None, caption_status=None):
        self.transitions[video_id] = (new_state, reason, caption_status)


def no_captions(candidates):
    for c in candidates:
        c.caption_status = "none"


def test_hard_filter_rejects_live_and_unembeddable():
    assert F.hard_and_rule_filter(cand(live=True)) == (False, "not_vod")
    assert F.hard_and_rule_filter(cand(embeddable=False)) == (False, "not_embeddable")


def test_hard_filter_rejects_bad_duration():
    ok, reason = F.hard_and_rule_filter(cand(duration_ms=0))
    assert not ok and reason == "too_long"
    ok, reason = F.hard_and_rule_filter(cand(duration_ms=F.MAX_DURATION_MS + 1))
    assert not ok and reason == "too_long"


def test_title_blacklist_applies_only_off_whitelist():
    ok, reason = F.hard_and_rule_filter(cand(title="김치찌개 먹방"))
    assert not ok and reason.startswith("rule_blacklist:")
    # 화이트리스트 채널은 규칙 스킵
    ok, _ = F.hard_and_rule_filter(cand(title="김치찌개 먹방", from_whitelist=True))
    assert ok


def test_llm_verdicts_delegates_to_injected_judge():
    seen = {}

    def judge(block: str) -> dict:
        seen["block"] = block
        return {"verdicts": [{"videoId": "v1", "isRecipe": True, "isSingleDish": True,
                              "dishName": "김치찌개", "confidence": 0.9}]}

    verdicts = F.llm_verdicts([cand("v1", description="줄바꿈\n포함 설명")], judge)
    assert verdicts["v1"]["dishName"] == "김치찌개"
    # judge는 후보 목록 텍스트 블록을 받는다 (한 줄에 한 후보, 줄바꿈은 평탄화)
    assert "videoId: v1" in seen["block"]
    assert "줄바꿈 포함 설명" in seen["block"]


def test_llm_verdicts_empty_pool_skips_judge():
    def judge(_):
        raise AssertionError("후보가 없으면 judge를 호출하지 않는다")
    assert F.llm_verdicts([], judge) == {}


def test_run_filter_transitions_and_ranking():
    candidates = [
        cand("good1", view_count=1_000_000, from_whitelist=True),
        cand("good2", channel_title="다른채널"),
        cand("mukbang", title="김치찌개 먹방"),          # 규칙 컷
        cand("notrecipe", channel_title="리뷰채널2"),     # LLM 컷
    ]

    def judge(block: str) -> dict:
        assert "mukbang" not in block, "하드 컷 후보는 judge에 넘기지 않는다"
        return {"verdicts": [
            {"videoId": "good1", "isRecipe": True, "isSingleDish": True,
             "dishName": "김치찌개", "confidence": 0.9},
            {"videoId": "good2", "isRecipe": True, "isSingleDish": True,
             "dishName": "된장찌개", "confidence": 0.8},
            {"videoId": "notrecipe", "isRecipe": False, "isSingleDish": False,
             "reason": "제품 리뷰"},
        ]}

    history = FakeHistory()
    result = F.run_filter(candidates, judge=judge, history=history,
                          top_n=1, caption_checker=no_captions)

    # 통과 목록: 상위 1건만, 스코어 내림차순 (good1이 화이트리스트+조회수로 우위)
    assert [r["videoId"] for r in result] == ["good1"]

    assert history.transitions["mukbang"][0] == F.FILTERED_OUT
    assert history.transitions["mukbang"][1].startswith("rule_blacklist:")
    assert history.transitions["notrecipe"][0] == F.FILTERED_OUT
    assert "llm_rejected" in history.transitions["notrecipe"][1]
    assert history.transitions["good1"][0] == F.QUEUED
    assert history.transitions["good2"][0] == F.DEFERRED, "top_n 밖은 deferred로 미룬다"


def test_score_weights():
    v = {"confidence": 1.0}
    c = cand(from_whitelist=True, view_count=1_000_000)
    c.caption_status = "manual"
    # manual 2.0 + whitelist 2.0 + log10(1e6)/2 = 3.0 + conf 3.0
    assert F.score(c, v) == 10.0
    c2 = cand()
    c2.caption_status = "none"
    assert F.score(c2, {"confidence": 0}) == 0.0
