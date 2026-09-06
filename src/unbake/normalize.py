"""결정적 후처리 — 계량 표기 정규화·경계 패딩·분량 근거 구간 (기존 저장소에서 이식).

검증된 로직 — 동작을 바꾸지 않는다. 새 아키텍처에서는 IR→DTO 매핑에서만 적용해
원본 claim을 보존한다 (docs/architecture.md).
"""
import re

# 경계 여유 패딩 (2026-08-06 확정, 같은 날 조정) — **딱 붙은 경계에만** +400ms.
# 이미 겹쳐 있거나(LLM이 여유를 준 경우) 갭이 있는(필러 스킵 의도) 경계는 존중한다.
# LLM 재량에 맡기지 않고 결정적 후처리로 보장한다.
BOUNDARY_PAD_MS = 400


def apply_boundary_padding(recipe: dict, pad_ms: int = BOUNDARY_PAD_MS) -> int:
    """인접 단계와 **완전히 붙어 있는**(end == 다음 start) 경계의 end만 +pad_ms 연장.

    - 겹침이 이미 있으면 그대로 둠 / 갭(불연속)도 그대로 둠 (스킵 의도 존중)
    - 다음 단계 end를 침범하지 않음 (중첩 금지 유지)
    - 마지막 단계는 경계가 없으므로 건드리지 않음
    반환: 실제로 연장된 단계 수.
    """
    steps = recipe.get("steps", [])
    dur = (recipe.get("video") or {}).get("durationMs")
    padded = 0
    for i in range(len(steps) - 1):
        s, nxt = steps[i], steps[i + 1]
        if s.get("videoEndMs") is None or nxt.get("videoStartMs") is None:
            continue
        if s["videoEndMs"] != nxt["videoStartMs"]:
            continue   # 겹침·갭 경계는 존중
        new_end = min(s["videoEndMs"] + pad_ms, nxt["videoEndMs"] - 100)
        if dur:
            new_end = min(new_end, dur)
        if new_end > s["videoEndMs"]:
            s["videoEndMs"] = new_end
            padded += 1
    return padded


# 영어 계량 표기 → 한국어 (환산은 하지 않는다 — 표기만 바꾼다).
# 순서가 중요하다: tbsp/tsp를 먼저 잡아야 맨 뒤 단문자 T/t 규칙이 오작동하지 않는다.
# 대소문자 구분: T=큰술, t=작은술 (관례) — 그래서 IGNORECASE를 쓰지 않는다.
_AMOUNT_UNIT_RULES = [
    (re.compile(r"(?<![A-Za-z])(\d+(?:[./]\d+)?)\s*(?:tbsp|tablespoons?)\b", re.IGNORECASE),
     r"\1큰술"),
    (re.compile(r"(?<![A-Za-z])(\d+(?:[./]\d+)?)\s*(?:tsp|teaspoons?)\b", re.IGNORECASE),
     r"\1작은술"),
    (re.compile(r"(?<![A-Za-z])(\d+(?:[./]\d+)?)\s*spoons?\b", re.IGNORECASE), r"\1스푼"),
    (re.compile(r"(?<![A-Za-z])(\d+(?:[./]\d+)?)\s*T(?![A-Za-z])"), r"\1큰술"),
    (re.compile(r"(?<![A-Za-z])(\d+(?:[./]\d+)?)\s*t(?![A-Za-z])"), r"\1작은술"),
    # '숟가락'은 초기 산출물에 남은 옛 표기 — 서비스 표준은 '큰술' (2026-08-07 확정).
    # '밥숟가락'·'밥숟갈'은 다른 계량이므로 건드리지 않는다.
    (re.compile(r"(?<!밥)(\d+(?:[./]\d+)?)\s*숟가락"), r"\1큰술"),
]
# 분량 표기는 **소수로 통일한다** (2026-08-07 사용자 확정).
# 영상마다 '0.5큰술'/'1/2큰술'/'1과 1/2큰술'/'⅔큰술'이 섞여 들어와 하나로 고정한다.
#   1/2큰술 → 0.5큰술 / 1과 1/2큰술 → 1.5큰술 / ⅔큰술 → 0.7큰술
# 유니코드 분수(½ ⅔ …)는 실제 설명란에 등장하므로 먼저 ASCII 분수로 편다.
_VULGAR = {"½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
           "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8"}
_VULGAR_RE = re.compile("([" + "".join(_VULGAR) + "])")

# 혼합수('1과 1/2', '1 1/2')를 단독 분수('1/2')보다 먼저 잡아야 한다
_MIXED_RE = re.compile(r"(?<![\d./])(\d+)\s*(?:과|와)?\s+(\d+)/(\d+)(?![\d/])")
_FRACTION_RE = re.compile(r"(?<![\d./])(\d+)/(\d+)(?![\d/])")
# LLM이 이미 '0.33큰술'로 뽑아온 경우도 같은 기준으로 다시 적는다
_DECIMAL_RE = re.compile(r"(?<![\d./])(\d*\.\d+)(?![\d/])")

# 단위를 바꾸면 뒤따르는 조사가 어긋난다 — 'T를'(모음 끝)이 '큰술를'이 된다.
# 치환한 단위는 전부 받침으로 끝나므로 을/이/은으로 교정하면 된다.
_PARTICLE_FIX = re.compile(r"(큰술|작은술|스푼)(를|가|는)")
_PARTICLE_MAP = {"를": "을", "가": "이", "는": "은"}


def _fmt_number(value: float) -> str:
    """소수 표기 — 딱 떨어지면 그대로, 아니면 **소수 첫째 자리**.

    1/3 → 0.3, 2/3 → 0.7, 0.33 → 0.3 (0.33·0.67은 요리 분량에 과한 정밀도다 — 2026-08-07 확정).
    예외는 0.25 배수(1/4·3/4·1.25…) — 계량컵의 관용 표기라 둘째 자리를 살린다.
    """
    if abs(round(value, 1) - value) < 1e-9:                 # 0.5, 1.5, 100.5 …
        return f"{value:.1f}".rstrip("0").rstrip(".")
    if abs(value * 4 - round(value * 4)) < 1e-9:            # 0.25, 0.75, 1.25 …
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{value:.1f}".rstrip("0").rstrip(".")           # 0.33 → 0.3, 0.67 → 0.7


def _expand_vulgar(text: str) -> str:
    """'⅔큰술' → '2/3큰술', '1½' → '1 1/2' (숫자 뒤면 공백을 넣어 혼합수로 만든다)."""
    def rep(m):
        i = m.start()
        prefix = " " if i > 0 and text[i - 1].isdigit() else ""
        return prefix + _VULGAR[m.group(1)]
    return _VULGAR_RE.sub(rep, text)


def _mixed_to_decimal(m: "re.Match") -> str:
    """'1과 1/2' → '1.5'."""
    whole, num, den = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if den == 0:
        return m.group(0)
    return _fmt_number(whole + num / den)


def _fraction_to_decimal(m: "re.Match") -> str:
    """'1/2' → '0.5', '2/3' → '0.7'."""
    num, den = int(m.group(1)), int(m.group(2))
    if den == 0:
        return m.group(0)
    return _fmt_number(num / den)


def normalize_amount(text: str) -> str:
    """계량 표기 통일 — 영어 단위는 한국어로, **분량은 전부 소수로**.

    '8T' → '8큰술', '1 tsp' → '1작은술',
    '1/2큰술' → '0.5큰술', '1과 1/2큰술' → '1.5큰술', '⅔큰술' → '0.7큰술'.
    단위 환산은 하지 않는다 (표기만 바꾼다).
    """
    for pat, rep in _AMOUNT_UNIT_RULES:
        new = pat.sub(rep, text)
        if new != text:
            new = _PARTICLE_FIX.sub(lambda m: m.group(1) + _PARTICLE_MAP[m.group(2)], new)
        text = new
    text = _expand_vulgar(text)                          # ⅔ → 2/3, 1½ → 1 1/2
    text = _MIXED_RE.sub(_mixed_to_decimal, text)        # 1과 1/2 → 1.5 (분수보다 먼저)
    text = _FRACTION_RE.sub(_fraction_to_decimal, text)  # 1/2 → 0.5
    return _DECIMAL_RE.sub(                              # 0.33 → 0.3 (이미 소수인 것도 통일)
        lambda m: _fmt_number(float(m.group(1))), text).strip()


def normalize_units(recipe: dict) -> int:
    """산출물 전체(재료 amount + details 문장)의 계량 단위를 한국어로 정규화.

    설명란을 1순위 근거로 쓰면서 생긴 문제(2026-08-07): 설명란이 '8T'로 적힌 채널이면
    그 표기가 그대로 실려 앱에 'T'가 노출된다. 프롬프트 지시만으로는 새는 규칙이라
    결정적 후처리로 옮겼다 (경계 패딩과 같은 취급).
    반환: 바뀐 문자열 수.
    """
    n = 0
    for ing in recipe.get("ingredients", []):
        amt = ing.get("amount")
        if amt:
            fixed = normalize_amount(amt)
            if fixed != amt:
                ing["amount"] = fixed
                n += 1
    for step in recipe.get("steps", []):
        for i, d in enumerate(step.get("details", [])):
            fixed = normalize_amount(d)
            if fixed != d:
                step["details"][i] = fixed
                n += 1
    return n


def _base_name(name: str) -> str:
    """'화자오(산초)' → '화자오', '물(전분물용)' → '물' — 단계 텍스트 매칭용."""
    return name.split("(")[0].strip()


def find_amount_windows(recipe: dict, target_names: list[str],
                        pad_ms: int = 2000) -> list[tuple[int, int]]:
    """대상 재료가 언급되는 단계 구간(±pad)을 찾아 병합. 못 찾으면 전체 구간."""
    duration = (recipe.get("video") or {}).get("durationMs") or 0
    windows: list[tuple[int, int]] = []
    for name in target_names:
        base = _base_name(name)
        for s in recipe.get("steps", []):
            text = s.get("title", "") + " " + " ".join(s.get("details", []))
            if base and base in text:
                windows.append((max(0, s["videoStartMs"] - pad_ms),
                                min(duration or s["videoEndMs"] + pad_ms,
                                    s["videoEndMs"] + pad_ms)))
    if not windows:   # 어느 단계에도 안 나오는 재료 → 전체 커버
        end = duration or max((s["videoEndMs"] for s in recipe.get("steps", [])), default=0)
        return [(0, end)] if end else []
    # 병합
    windows.sort()
    merged = [windows[0]]
    for start, end in windows[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
