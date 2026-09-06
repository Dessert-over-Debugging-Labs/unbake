"""영상 설명란 활용 — 레시피 정보 밀도 점수화 (2026-08-07 신설, 이식).

설명란에 재료·분량·조리 순서를 통째로 적어두는 채널이 있다. 이 텍스트는 자막보다 정확하다
(자동 생성 자막의 오탈자가 없고, 분량이 숫자로 명시된다). ③ 추출에서 분량 근거로 쓰고,
동시에 **채널 화이트리스트 승격 근거**로도 쓴다 — 설명란이 충실한 채널은 계속 그렇기 때문이다.

LLM 없이 결정적으로 점수화한다. 근거(signals)를 사람에게 그대로 보여주기 위함이다.
"""
import re

# 분량 표기: 숫자 + 단위 (한국어 계량 단위 포함)
AMOUNT_RE = re.compile(
    r"\d+\s*(?:/\d+\s*)?"
    r"(?:g|kg|ml|mL|L|리터|cc|큰술|작은술|스푼|숟갈|밥숟갈|티스푼|컵|줌|꼬집|"
    r"개|알|쪽|장|봉|봉지|팩|캔|모|단|마리|공기|대)\b"
)
# 재료 섹션 헤더 — "[재료]", "▶ 재료", "🧂 재료", "* 고기 양념 :" 등
# 머리말 장식은 종류가 끝없다(이모지 포함) — 문자·개행이 아닌 것 0~4자를 접두로 허용한다
ING_HEADER_RE = re.compile(r"(?:^|\n)[^\w\n]{0,4}"
                           r"(재\s?료|양념|양념장|소스|만드는\s?법|조리\s?법|레시피)"
                           r"\s*[\]\)】:：]?", re.MULTILINE)
# 번호 매긴 조리 순서 — "1." "1)" "①"
STEP_NUM_RE = re.compile(r"(?:^|\n)\s*(?:\d{1,2}\s*[.)]|[①-⑳])\s*\S", re.MULTILINE)
# 노이즈 — 구독 유도·링크·해시태그·비즈니스 문의
NOISE_RE = re.compile(
    r"https?://|www\.|#\S+|구독|좋아요|알림\s?설정|협찬|비즈니스\s?문의|문의\s?:|"
    r"인스타그램|instagram|채널\s?멤버십", re.IGNORECASE)


def strip_noise(text: str) -> str:
    """링크·구독 유도 등 레시피와 무관한 줄을 걷어낸 본문."""
    kept = [ln for ln in (text or "").splitlines() if ln.strip() and not NOISE_RE.search(ln)]
    return "\n".join(kept)


def score_description(text: str) -> dict:
    """설명란의 레시피 정보 밀도 → {score, level, signals, amountCount, bodyChars}.

    score 0.0~1.0. level: rich(0.6+) / partial(0.3+) / thin(0.1+) / none.
    signals는 사람이 읽는 근거 문장 — 대시보드 화이트리스트 카드에 그대로 노출된다.
    """
    body = strip_noise(text or "")
    signals: list[str] = []
    if not body.strip():
        return {"score": 0.0, "level": "none", "signals": ["설명란이 비어 있거나 링크·해시태그뿐"],
                "amountCount": 0, "bodyChars": 0}

    amounts = AMOUNT_RE.findall(body)
    n_amount = len(amounts)
    has_header = bool(ING_HEADER_RE.search(body))
    n_steps = len(STEP_NUM_RE.findall(body))
    chars = len(body)

    score = 0.0
    if n_amount >= 5:
        score += 0.45
        signals.append(f"분량 표기 {n_amount}개 (재료 분량이 숫자로 적혀 있음)")
    elif n_amount >= 2:
        score += 0.25
        signals.append(f"분량 표기 {n_amount}개")
    elif n_amount == 1:
        score += 0.1
        signals.append("분량 표기 1개")

    if has_header:
        score += 0.25
        signals.append("'재료'·'양념'·'만드는 법' 섹션 머리말 있음")

    if n_steps >= 3:
        score += 0.2
        signals.append(f"번호 매긴 조리 순서 {n_steps}단계")
    elif n_steps >= 1:
        score += 0.08

    if chars >= 300:
        score += 0.1
        signals.append(f"본문 {chars}자 (링크·해시태그 제외)")
    elif chars >= 120:
        score += 0.05

    score = round(min(score, 1.0), 2)
    level = ("rich" if score >= 0.6 else "partial" if score >= 0.3
             else "thin" if score >= 0.1 else "none")
    if level == "none" and not signals:
        signals.append("레시피 정보로 볼 만한 내용 없음")
    return {"score": score, "level": level, "signals": signals,
            "amountCount": n_amount, "bodyChars": chars}


LEVEL_HINT = {
    "rich": "이 설명란에는 재료·분량·순서가 정리돼 있다. "
            "**분량과 재료 목록의 1순위 근거로 삼아라.**",
    "partial": "이 설명란에 일부 재료·분량 정보가 있다. "
               "자막·프레임과 교차 확인해 보강 근거로 써라.",
    "thin": "이 설명란은 레시피 정보가 희박하다. 참고만 하고 자막·프레임을 우선하라.",
    "none": "",
}


def description_block(meta: dict) -> str:
    """프롬프트에 주입할 설명란 블록 — 원문 + 밀도 판정 + 사용 지침."""
    raw = (meta or {}).get("description") or ""
    if not raw.strip():
        return "(설명란 없음 — 자막·프레임만으로 분석)"
    s = score_description(raw)
    hint = LEVEL_HINT.get(s["level"], "")
    head = f"밀도 판정: {s['level']} (score {s['score']}) — {', '.join(s['signals'])}"
    return f"{head}\n{hint}\n\n```\n{raw.strip()}\n```".strip()
