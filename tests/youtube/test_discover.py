"""① 탐색 트랙 B — 화이트리스트 채널 백필.

이전 구현은 매 실행 최신 페이지만 훑어, 한 번 수집된 뒤에는 신규 업로드 전까지
아무것도 나오지 않았다 (과거 카탈로그 도달 불가). 커서 기반 백필이 그 회귀를 막는다.

sqlite 결합을 끊은 이식 — 커서는 InMemoryCursorStore(주입 인터페이스 구현)로 검증한다.
"""
import json

import pytest

from unbake.adapters.youtube import discover as D
from unbake.adapters.youtube.discover import InMemoryCursorStore

API_KEY = "test-key"


@pytest.fixture
def seeds(tmp_path, monkeypatch):
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "channels.json").write_text(
        json.dumps({"channels": [{"channelId": "CH1", "name": "테스트채널"}]}),
        encoding="utf-8")
    monkeypatch.setattr(D, "SEEDS_DIR", seeds)
    return seeds


def fake_api(pages, *, uploads="UU_CH1"):
    """playlistItems 페이지 사슬을 흉내낸다. pages: [(videoIds, nextToken), ...]"""
    calls = []

    def _get(api_key, path, **params):
        calls.append((path, params.get("pageToken")))
        if path == "channels":
            return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": uploads}}}]}
        if path == "playlistItems":
            token = params.get("pageToken")
            idx = 0 if token is None else next(
                i + 1 for i, p in enumerate(pages) if p[1] == token)
            vids, nxt = pages[idx]
            return {"items": [{"snippet": {"resourceId": {"videoId": v}}} for v in vids],
                    **({"nextPageToken": nxt} if nxt else {})}
        raise AssertionError(f"예상치 못한 호출: {path}")

    return _get, calls


def test_backfill_walks_past_the_first_page(seeds, monkeypatch):
    pages = [(["a1", "a2"], "T1"), (["b1", "b2"], "T2"), (["c1"], None)]
    _get, _ = fake_api(pages)
    monkeypatch.setattr(D, "_get", _get)
    cursors = InMemoryCursorStore()

    got = {c.video_id for c in D.channel_track(API_KEY, cursors, backfill_pages=1)}
    # 헤드(a) + 백필 1페이지(a) — 첫 실행은 커서가 없어 헤드부터 백필한다
    assert "a1" in got

    got2 = {c.video_id for c in D.channel_track(API_KEY, cursors, backfill_pages=1)}
    assert "b1" in got2 and "b2" in got2, "두 번째 실행은 과거로 넘어가야 한다"

    got3 = {c.video_id for c in D.channel_track(API_KEY, cursors, backfill_pages=1)}
    assert "c1" in got3, "세 번째 실행에서 마지막 페이지까지 도달해야 한다"


def test_exhausted_channel_only_fetches_head(seeds, monkeypatch):
    pages = [(["a1"], None)]     # 단일 페이지 채널
    _get, calls = fake_api(pages)
    monkeypatch.setattr(D, "_get", _get)
    cursors = InMemoryCursorStore()

    D.channel_track(API_KEY, cursors, backfill_pages=3)
    row = cursors.channel_cursor("CH1")
    assert row["exhausted"] == 1

    calls.clear()
    D.channel_track(API_KEY, cursors, backfill_pages=3)
    playlist_calls = [c for c in calls if c[0] == "playlistItems"]
    assert len(playlist_calls) == 1, "끝까지 훑은 채널은 헤드 1회만 조회한다"


def test_uploads_playlist_id_is_cached(seeds, monkeypatch):
    pages = [(["a1"], None)]
    _get, calls = fake_api(pages)
    monkeypatch.setattr(D, "_get", _get)
    cursors = InMemoryCursorStore()

    D.channel_track(API_KEY, cursors, backfill_pages=1)
    calls.clear()
    D.channel_track(API_KEY, cursors, backfill_pages=1)
    assert not [c for c in calls if c[0] == "channels"], \
        "업로드 재생목록 id는 채널당 고정 — 두 번째 실행에서 재조회하지 않는다"


def test_reset_cursor_restarts_backfill(seeds, monkeypatch):
    pages = [(["a1"], "T1"), (["b1"], None)]
    _get, _ = fake_api(pages)
    monkeypatch.setattr(D, "_get", _get)
    cursors = InMemoryCursorStore()

    D.channel_track(API_KEY, cursors, backfill_pages=1)
    D.channel_track(API_KEY, cursors, backfill_pages=1)      # exhausted 도달
    assert cursors.channel_cursor("CH1")["exhausted"] == 1
    cursors.reset_channel_cursor("CH1")
    assert cursors.channel_cursor("CH1")["exhausted"] == 0
    assert cursors.channel_cursor("CH1")["page_token"] is None


def cand(vid, source, whitelist=True):
    return D.Candidate(video_id=vid, source=source, from_whitelist=whitelist)


def test_round_robin_spreads_across_sources():
    """채널별로 뭉쳐 들어온 후보를 번갈아 재배열 — 앞쪽 채널 독식 방지."""
    items = ([cand(f"a{i}", "channel:A") for i in range(5)]
             + [cand(f"b{i}", "channel:B") for i in range(5)]
             + [cand(f"c{i}", "channel:C") for i in range(5)])
    out = [c.video_id for c in D._round_robin(items)]
    assert out[:3] == ["a0", "b0", "c0"]
    assert out[3:6] == ["a1", "b1", "c1"]
    # 상위 6칸만 잘라도 세 채널이 모두 들어온다 (이전에는 a만 6개였다)
    assert {v[0] for v in out[:6]} == {"a", "b", "c"}


def test_round_robin_handles_uneven_groups():
    items = ([cand("a0", "channel:A")]
             + [cand(f"b{i}", "channel:B") for i in range(3)])
    out = [c.video_id for c in D._round_robin(items)]
    assert out == ["a0", "b0", "b1", "b2"]
    assert len(out) == 4          # 유실 없음


def test_round_robin_empty():
    assert D._round_robin([]) == []
