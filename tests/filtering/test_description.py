"""설명란 밀도 점수화 — ③ 추출 근거·채널 승격 근거의 공통 입력."""
from unbake.filtering.description import description_block, score_description, strip_noise

RICH = """#소불고기 #황금레시피

🧂 재료
소불고기 600g, 양파 1/2개(100g), 대파 1대, 느타리버섯 100g

* 고기 양념 :
설탕 1큰술, 맛술 2큰술, 간장 8큰술, 다진 마늘 1큰술

1. 고기를 양념에 재운다
2. 야채를 썬다
3. 센 불에 볶는다

구독과 좋아요 부탁드립니다
https://instagram.com/example
"""

NOISE_ONLY = """구독과 좋아요!
https://youtube.com/@example
#요리 #레시피 #집밥
비즈니스 문의 : mail@example.com
"""


def test_rich_description_scores_high():
    s = score_description(RICH)
    assert s["level"] == "rich" and s["score"] >= 0.6
    assert s["amountCount"] >= 5
    assert any("분량 표기" in sig for sig in s["signals"])
    assert any("머리말" in sig for sig in s["signals"])


def test_emoji_prefixed_header_detected():
    """'🧂 재료'처럼 이모지가 붙은 머리말도 섹션으로 인식해야 한다 (실데이터에서 발견)."""
    s = score_description("🧂 재료\n간장 2큰술, 설탕 1큰술")
    assert any("머리말" in sig for sig in s["signals"])


def test_noise_only_description_scores_none():
    s = score_description(NOISE_ONLY)
    assert s["level"] == "none" and s["score"] == 0.0


def test_empty_description():
    s = score_description("")
    assert s["level"] == "none" and s["signals"]


def test_strip_noise_drops_links_and_hashtags():
    body = strip_noise(RICH)
    assert "instagram" not in body and "구독" not in body
    assert "간장 8큰술" in body


def test_description_block_has_hint_and_raw_text():
    block = description_block({"description": RICH})
    assert "밀도 판정: rich" in block
    assert "1순위 근거" in block          # rich 레벨 사용 지침
    assert "간장 8큰술" in block          # 원문 그대로 전달


def test_description_block_without_description():
    assert "설명란 없음" in description_block({"description": ""})
    assert "설명란 없음" in description_block({})
