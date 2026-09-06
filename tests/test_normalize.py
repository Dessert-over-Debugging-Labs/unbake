"""결정적 후처리 회귀 — 계량 정규화·경계 패딩·분량 근거 구간 (기존 저장소에서 이식)."""
from unbake.normalize import (
    apply_boundary_padding,
    find_amount_windows,
    normalize_amount,
    normalize_units,
)


def test_find_amount_windows():
    recipe = {
        "video": {"durationMs": 80000},
        "steps": [
            {"title": "고기와 양념 볶기", "videoStartMs": 8000, "videoEndMs": 23000,
             "details": ["두반장 1스푼을 넣는다"]},
            {"title": "국물 만들기", "videoStartMs": 23000, "videoEndMs": 32000,
             "details": ["물을 붓는다"]},
            {"title": "마무리", "videoStartMs": 60000, "videoEndMs": 70000,
             "details": ["화자오를 뿌린다"]},
        ],
    }
    # 두반장 → 1단계, 화자오(산초) → 괄호 제거 매칭으로 3단계
    w = find_amount_windows(recipe, ["두반장", "화자오(산초)"])
    assert w == [(6000, 25000), (58000, 72000)]
    # 어느 단계에도 없는 재료 → 전체 구간
    assert find_amount_windows(recipe, ["치킨스톡"]) == [(0, 80000)]
    # 인접 구간 병합
    w = find_amount_windows(recipe, ["두반장", "물"])
    assert w == [(6000, 34000)]


def test_apply_boundary_padding():
    recipe = {
        "video": {"durationMs": 60000},
        "steps": [
            {"videoStartMs": 5000, "videoEndMs": 14000},   # 다음과 딱 붙음 → 패딩
            {"videoStartMs": 14000, "videoEndMs": 20000},  # 다음과 3초 갭 → 존중
            {"videoStartMs": 23000, "videoEndMs": 30000},  # 다음과 이미 1초 겹침 → 존중
            {"videoStartMs": 29000, "videoEndMs": 59800},  # 마지막 → 경계 없음, 그대로
        ],
    }
    n = apply_boundary_padding(recipe, pad_ms=400)
    s = recipe["steps"]
    assert s[0]["videoEndMs"] == 14400   # 딱 붙은 경계만 +400ms
    assert s[1]["videoEndMs"] == 20000   # 갭 존중
    assert s[2]["videoEndMs"] == 30000   # 기존 겹침 존중
    assert s[3]["videoEndMs"] == 59800   # 마지막 그대로
    assert n == 1


def test_normalize_amount_english_units():
    """설명란이 'T'/'tsp'로 적힌 채널이 있다 — 표기만 한국어로 (환산 금지)."""
    n = normalize_amount
    assert n("8T") == "8큰술"
    assert n("1t") == "1작은술"
    assert n("2 tbsp") == "2큰술"
    assert n("3 tsp") == "3작은술"
    assert n("1/2T") == "0.5큰술"      # 단위 변환 + 소수 통일이 함께 적용된다
    assert n("2spoons") == "2스푼"


def test_normalize_amount_leaves_metric_and_korean():
    n = normalize_amount
    for keep in ("100ml", "600g", "1kg", "1개", "2큰술", "영상 참고"):
        assert n(keep) == keep


def test_normalize_amount_fixes_particle():
    """단위를 바꾸면 조사가 어긋난다 — 'T를'(모음)이 '큰술를'이 되면 안 된다."""
    n = normalize_amount
    assert n("진간장 8T를 넣는다") == "진간장 8큰술을 넣는다"
    assert n("미림 4T가 들어간다") == "미림 4큰술이 들어간다"
    # 치환이 없었으면 기존 문장은 건드리지 않는다 (보수적)
    assert n("원래 큰술를 쓴 문장") == "원래 큰술를 쓴 문장"


def test_normalize_units_covers_ingredients_and_details():
    recipe = {
        "ingredients": [{"name": "진간장", "amount": "8T"},
                        {"name": "물", "amount": "100ml"},
                        {"name": "당근", "amount": None}],
        "steps": [{"details": ["진간장 8T를 넣는다", "물 100ml를 붓는다"]}],
    }
    n = normalize_units(recipe)
    assert recipe["ingredients"][0]["amount"] == "8큰술"
    assert recipe["ingredients"][1]["amount"] == "100ml"   # 미터법 유지
    assert recipe["steps"][0]["details"][0] == "진간장 8큰술을 넣는다"
    assert recipe["steps"][0]["details"][1] == "물 100ml를 붓는다"
    assert n == 2   # amount 1곳 + details 1곳


def test_fractions_become_decimals():
    """분량은 소수로 통일 (2026-08-07 사용자 확정) — 영상마다 표기가 갈린다."""
    n = normalize_amount
    assert n("1/2큰술") == "0.5큰술"
    assert n("1/4컵") == "0.25컵"
    assert n("3/4컵") == "0.75컵"
    assert n("2/3큰술") == "0.7큰술"       # 순환소수는 첫째 자리로
    assert n("1/3컵") == "0.3컵"


def test_mixed_numbers_become_decimals():
    n = normalize_amount
    assert n("1과 1/2큰술") == "1.5큰술"
    assert n("1 1/2큰술") == "1.5큰술"
    assert n("1½큰술") == "1.5큰술"
    assert n("2와 1/2컵") == "2.5컵"
    assert n("1과 1/3컵") == "1.3컵"


def test_vulgar_fractions_expanded():
    """유니코드 분수는 실제 설명란에 등장한다 ('다진마늘 ⅔큰술')."""
    n = normalize_amount
    assert n("⅔큰술") == "0.7큰술"
    assert n("½큰술") == "0.5큰술"
    assert n("다진마늘 ⅔큰술을 넣는다") == "다진마늘 0.7큰술을 넣는다"


def test_decimals_and_metric_untouched():
    n = normalize_amount
    for keep in ("0.5큰술", "1.5큰술", "0.3큰술", "0.25컵", "0.75컵",
                 "0.5g", "300g", "100.5g", "1개", "1L"):
        assert n(keep) == keep


def test_decimal_normalization_applies_to_details():
    recipe = {"ingredients": [{"name": "설탕", "amount": "1/2큰술"},
                              {"name": "소금", "amount": "0.5g"}],
              "steps": [{"details": ["설탕 1/2큰술을 넣는다", "물 400ml를 붓는다"]}]}
    normalize_units(recipe)
    assert recipe["ingredients"][0]["amount"] == "0.5큰술"
    assert recipe["ingredients"][1]["amount"] == "0.5g"
    assert recipe["steps"][0]["details"][0] == "설탕 0.5큰술을 넣는다"
    assert recipe["steps"][0]["details"][1] == "물 400ml를 붓는다"


def test_over_precise_decimals_rounded_to_one_place():
    """0.33큰술은 요리 분량에 과한 정밀도 — 0.3으로 (2026-08-07 사용자 확정)."""
    n = normalize_amount
    assert n("0.33컵") == "0.3컵"
    assert n("0.67큰술") == "0.7큰술"
    assert n("1.33컵") == "1.3컵"
    assert n("소금 0.33작은술 넣기") == "소금 0.3작은술 넣기"


def test_quarter_measures_keep_two_places():
    """0.25 배수는 계량컵 관용 표기라 둘째 자리를 살린다."""
    n = normalize_amount
    assert n("1/4컵") == "0.25컵"
    assert n("3/4컵") == "0.75컵"
    assert n("1과 1/4컵") == "1.25컵"
    assert n("1.25L") == "1.25L"


def test_old_spoon_term_normalized():
    """초기 산출물에 남은 '숟가락'은 서비스 표준 '큰술'로 (2026-08-07 확정)."""
    n = normalize_amount
    assert n("2숟가락") == "2큰술"
    assert n("냄비에 식용유 2숟가락을 두른다.") == "냄비에 식용유 2큰술을 두른다."
    assert n("1/2숟가락") == "0.5큰술"
    assert n("1밥숟가락") == "1밥숟가락"      # 밥숟가락은 다른 계량 — 건드리지 않는다
