"""공용 유틸 — JSON 추출·URL 파싱·다양성 선정 (기존 저장소에서 이식)."""
import pytest

from unbake.util import JsonExtractionError, extract_json, parse_video_id, select_diverse


def test_extract_json_from_fenced_block():
    text = "결과입니다.\n```json\n{\"a\": 1}\n```\n끝."
    assert extract_json(text) == {"a": 1}


def test_extract_json_from_bare_object_with_prose():
    text = "서두 문장이 있어도 {\"verdicts\": [{\"ok\": true}]} 뒤 문장도 무시한다"
    assert extract_json(text) == {"verdicts": [{"ok": True}]}


def test_extract_json_raises_when_missing():
    with pytest.raises(JsonExtractionError):
        extract_json("JSON이 전혀 없는 출력")


def cand(vid, channel, dish, dur_s, caption="auto", score=7.0):
    return {"videoId": vid, "channel": channel, "dishName": dish,
            "durationMs": dur_s * 1000, "caption": caption, "score": score}


def test_prefers_manual_caption_once():
    """수동 자막 1건은 스코어가 낮아도 우선 확보 (런북 규칙)."""
    cands = [cand("a", "A", "카레", 80, score=8.0), cand("b", "B", "찌개", 90, score=7.9),
             cand("m", "C", "덮밥", 400, caption="manual", score=7.0)]
    picked = select_diverse(cands, 2)
    assert any(p["caption"] == "manual" for p in picked)


def test_avoids_same_channel_and_dish():
    cands = [cand("a1", "뚝딱이형", "카레", 80, score=8.3),
             cand("a2", "뚝딱이형", "카레", 87, score=8.35),
             cand("b", "살림팝", "떡볶이", 26, score=6.9)]
    picked = select_diverse(cands, 2)
    assert len({p["channel"] for p in picked}) == 2
    assert len({p["dishName"] for p in picked}) == 2


def test_spreads_length_buckets():
    """같은 조건이면 초단편/중편/장편이 섞이도록."""
    cands = [cand(f"s{i}", f"CH{i}", f"요리{i}", 30, score=7.0) for i in range(3)] + \
            [cand("long", "CHL", "장편요리", 500, score=6.5)]
    picked = select_diverse(cands, 3)
    assert any(p["durationMs"] > 240_000 for p in picked)


def test_returns_all_when_pool_smaller():
    picked = select_diverse([cand("a", "A", "x", 60)], 5)
    assert len(picked) == 1


def test_parse_video_id_formats():
    vid = "CgapOjKdo9I"
    cases = [
        f"https://www.youtube.com/watch?v={vid}",
        f"https://youtu.be/{vid}",
        f"https://www.youtube.com/shorts/{vid}",
        f"https://m.youtube.com/watch?v={vid}&t=30s",
        f"https://www.youtube.com/embed/{vid}",
        f"  https://youtu.be/{vid}?si=abc  ",
        vid,
    ]
    for c in cases:
        assert parse_video_id(c) == vid, c


def test_parse_video_id_rejects_garbage():
    for bad in ["", "   ", "https://naver.com", "그냥 텍스트", None]:
        assert parse_video_id(bad) is None
