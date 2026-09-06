"""② 이용 제한 문구 감지 — 사전 동의가 필요한 채널을 통과시키지 않는다."""
import json

import pytest

from unbake.filtering import licensing as L

REAL_NOTICE = """🙂https://band.us/@foodgarden

✅영상에서 언급한 컵, 스푼은 계량도구입니다.
✅영상의 상업적 이용, 2차 편집 및 재 업로드를 금지합니다
🚫최근 무단도용 사례가 많이 발생하고 있습니다. 사전동의없는 레시피 도용을 금지합니다.

✅재료
감자1개
당근1/2개

⚠️이 영상은 '딸을위한레시피'에서 제작하였으며,
딸을위한레시피의 저작물을 동의없이 무단으로 침해할 경우
저작권법에 의해 처벌 대상이 될 수 있습니다. (All rights reserved)
"""

PLAIN = """오늘은 김치찌개를 만들어봤어요.

재료
김치 300g, 돼지고기 200g, 두부 1/2모

Music provided by 브금대통령
Artist : 오늘의 일기
Title : Sweet potato
구독과 좋아요 부탁드립니다!
"""


@pytest.fixture
def registry(tmp_path, monkeypatch):
    f = tmp_path / "consent-required-channels.json"
    monkeypatch.setattr(L, "REGISTRY", f)
    monkeypatch.setattr(L, "SEEDS_DIR", tmp_path)
    return f


def test_detects_real_restriction_notice():
    r = L.detect_restrictions(REAL_NOTICE)
    assert r["restricted"]
    kinds = {s["kind"] for s in r["signals"]}
    assert "상업적 이용 금지" in kinds
    assert "무단 도용 금지" in kinds
    assert "2차 편집·재업로드 금지" in kinds
    # 근거로 원문을 남겨야 사람이 판단할 수 있다
    assert any("금지합니다" in s["quote"] for s in r["signals"])


def test_plain_description_not_flagged():
    """음원 크레딧·구독 유도만 있는 평범한 설명란은 걸리면 안 된다 (오탐 방지)."""
    assert not L.detect_restrictions(PLAIN)["restricted"]
    assert not L.detect_restrictions("")["restricted"]


def test_short_notice_variant_detected():
    assert L.detect_restrictions("🚫 레시피와 영상의 무단 도용을 금지합니다.")["restricted"]


def test_check_candidate_blocks_and_records(registry):
    reason = L.check_candidate("CH_X", "제한채널", REAL_NOTICE, video_id="v1")
    assert reason and reason.startswith("consent_required")
    entries = L.load_registry()
    assert len(entries) == 1
    assert entries[0]["channelId"] == "CH_X"
    assert entries[0]["firstSeenVideoId"] == "v1"
    assert entries[0]["consentGranted"] is False


def test_check_candidate_passes_clean_channel(registry):
    assert L.check_candidate("CH_OK", "평범채널", PLAIN, video_id="v2") is None
    assert L.load_registry() == []


def test_registered_channel_blocks_even_without_notice(registry):
    """한 번 등록된 채널은 설명란이 비어 있는 다른 영상도 막는다."""
    L.check_candidate("CH_X", "제한채널", REAL_NOTICE, video_id="v1")
    reason = L.check_candidate("CH_X", "제한채널", "", video_id="v2")
    assert reason and "등록부에 있음" in reason


def test_record_channel_is_idempotent(registry):
    L.check_candidate("CH_X", "제한채널", REAL_NOTICE, video_id="v1")
    L.check_candidate("CH_X", "제한채널", REAL_NOTICE, video_id="v3")
    assert len(L.load_registry()) == 1


def test_consent_granted_channel_is_allowed_again(registry):
    """사전 동의를 받으면 consentGranted를 켜서 다시 수집한다."""
    L.check_candidate("CH_X", "제한채널", REAL_NOTICE, video_id="v1")
    data = json.loads(registry.read_text(encoding="utf-8"))
    data["channels"][0]["consentGranted"] = True
    registry.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert "CH_X" not in L.consent_required_ids()


def test_hard_filter_rejects_restricted_candidate(registry):
    from unbake.adapters.youtube.discover import Candidate
    from unbake.filtering.filter import hard_and_rule_filter
    c = Candidate(video_id="v1", title="김치찌개 레시피", channel_id="CH_X",
                  channel_title="제한채널", duration_ms=300_000,
                  description=REAL_NOTICE)
    ok, reason = hard_and_rule_filter(c)
    assert not ok and reason.startswith("consent_required")


def test_hard_filter_rejects_restricted_whitelist_channel(registry):
    """화이트리스트 채널이라도 예외 없다."""
    from unbake.adapters.youtube.discover import Candidate
    from unbake.filtering.filter import hard_and_rule_filter
    c = Candidate(video_id="v1", title="김치찌개 레시피", channel_id="CH_X",
                  channel_title="제한채널", duration_ms=300_000,
                  description=REAL_NOTICE, from_whitelist=True)
    ok, reason = hard_and_rule_filter(c)
    assert not ok and reason.startswith("consent_required")


def test_set_consent_toggles_block(registry):
    L.check_candidate("CH_X", "제한채널", REAL_NOTICE, video_id="v1")
    assert "CH_X" in L.consent_required_ids()
    assert L.set_consent("CH_X", True)["ok"]
    assert "CH_X" not in L.consent_required_ids()
    L.set_consent("CH_X", False)
    assert "CH_X" in L.consent_required_ids()


def test_set_consent_unknown_channel(registry):
    assert not L.set_consent("없는채널", True)["ok"]
