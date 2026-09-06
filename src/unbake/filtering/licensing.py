"""② 필터 — 이용 제한 문구 감지와 '사전 동의 필요' 채널 등록 (2026-08-07 신설, 이식).

설명란에 "상업적 이용 금지", "무단 도용 금지", "사전동의없는 레시피 도용을 금지합니다"처럼
**이용 조건을 명시한 채널**이 있다. 냄비는 상업 서비스이고 이 파이프라인은 레시피를 추출해
등록하므로, 그런 채널은 창작자의 사전 동의 없이 쓰지 않는다.

정책 (2026-08-07 사용자 확정):
- 감지되면 **통과시키지 않는다** — ②에서 filtered_out 처리
- 채널을 `seeds/consent-required-channels.json`에 근거와 함께 모아둔다.
  나중에 사전 동의를 받으면 그 목록에서 빼고 다시 수집한다

조리법 자체(재료·순서 같은 사실)는 저작권 보호 대상이 아니라는 게 통설이지만, 이건 법적
판단 이전에 **창작자가 명시적으로 거부 의사를 밝힌 경우**를 존중하는 운영 규칙이다.
"""
import json
import re
from datetime import UTC, datetime
from pathlib import Path

# 저장소 루트의 seeds/ — 테스트는 이 모듈 변수들을 monkeypatch한다
SEEDS_DIR = Path(__file__).resolve().parents[3] / "seeds"
REGISTRY = SEEDS_DIR / "consent-required-channels.json"

# 각 패턴은 (분류, 정규식). 명시적 '금지/제한' 의사가 드러나는 표현만 넣는다 —
# '저작권' 단어 하나로는 잡지 않는다 (음원 크레딧 등 오탐 방지).
RESTRICTION_PATTERNS = [
    ("상업적 이용 금지",
     re.compile(r"상업적\s*(?:인)?\s*이용[^\n]{0,20}?(?:금지|불가|금합니다|삼가)")),
    ("2차 편집·재업로드 금지",
     re.compile(r"(?:2\s*차\s*(?:편집|가공|저작)|재\s*업로드|재업로드|무단\s*편집)[^\n]{0,20}?"
                r"(?:금지|불가|금합니다)")),
    ("무단 도용 금지",
     re.compile(r"(?:무단\s*도용|도용|무단\s*사용|무단\s*이용)[^\n]{0,20}?(?:금지|불가|금합니다)")),
    ("사전 동의 요구",
     re.compile(r"(?:사전\s*)?동의\s*(?:없이|없는)[^\n]{0,30}?(?:금지|불가|침해|처벌)")),
    ("무단 전재·복제·배포 금지",
     re.compile(r"무단\s*(?:전재|복제|배포|전송)[^\n]{0,20}?(?:금지|불가|금합니다)")),
    ("저작권 침해 경고",
     re.compile(r"저작권법에\s*의(?:해|하여)[^\n]{0,20}?처벌")),
    ("All rights reserved", re.compile(r"all\s+rights\s+reserved", re.I)),
]


def detect_restrictions(text: str) -> dict:
    """설명란에서 이용 제한 문구를 찾는다 → {restricted, signals}.

    signals에는 분류와 **실제 문장**을 담는다 — 사람이 왜 걸렸는지 바로 보게 하기 위함이다.
    """
    signals: list[dict] = []
    for kind, pat in RESTRICTION_PATTERNS:
        m = pat.search(text or "")
        if not m:
            continue
        # 근거로 보여줄 원문 한 줄
        start = (text.rfind("\n", 0, m.start()) + 1)
        end = text.find("\n", m.end())
        quote = text[start:end if end != -1 else len(text)].strip()
        signals.append({"kind": kind, "quote": quote[:200]})
    return {"restricted": bool(signals), "signals": signals}


def _load() -> dict:
    if not REGISTRY.exists():
        return {"comment": "② 필터에서 이용 제한 문구가 감지된 채널 — "
                           "사전 동의 전까지 수집하지 않는다",
                "channels": []}
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def load_registry() -> list[dict]:
    return _load().get("channels", [])


def consent_required_ids() -> set:
    return {c.get("channelId") for c in load_registry() if not c.get("consentGranted")}


def record_channel(channel_id: str, channel_title: str, signals: list[dict], *,
                   video_id: str = "") -> dict:
    """감지된 채널을 등록 (멱등 — 이미 있으면 근거만 보강)."""
    if not channel_id:
        return {"ok": False, "reason": "channelId 없음"}
    data = _load()
    now = datetime.now(UTC).isoformat()
    for c in data["channels"]:
        if c.get("channelId") == channel_id:
            known = {s["kind"] for s in c.get("signals", [])}
            new = [s for s in signals if s["kind"] not in known]
            if new:
                c.setdefault("signals", []).extend(new)
                c["updatedAt"] = now
                REGISTRY.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
            return {"ok": True, "already": True, "channelId": channel_id}
    data["channels"].append({
        "channelId": channel_id,
        "name": channel_title or "(이름 미상)",
        "firstSeenVideoId": video_id,
        "signals": signals,
        "consentGranted": False,     # 사전 동의를 받으면 true로 바꾸고 다시 수집한다
        "addedAt": now,
    })
    SEEDS_DIR.mkdir(exist_ok=True)
    REGISTRY.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    return {"ok": True, "already": False, "channelId": channel_id,
            "count": len(data["channels"])}


def set_consent(channel_id: str, granted: bool) -> dict:
    """사전 동의 확보 여부를 표시 — granted면 다시 수집 대상이 된다."""
    data = _load()
    for c in data["channels"]:
        if c.get("channelId") == channel_id:
            c["consentGranted"] = bool(granted)
            c["consentUpdatedAt"] = datetime.now(UTC).isoformat()
            REGISTRY.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
            return {"ok": True, "channelId": channel_id, "consentGranted": bool(granted)}
    return {"ok": False, "reason": f"등록부에 없는 채널입니다: {channel_id}"}


def check_candidate(channel_id: str, channel_title: str, description: str, *,
                    video_id: str = "") -> str | None:
    """②에서 호출 — 제한이 감지되면 채널을 등록하고 탈락 사유 문자열을 돌려준다.

    통과시켜도 되면 None.
    """
    if channel_id and channel_id in consent_required_ids():
        return "consent_required: 사전 동의 필요 채널 (등록부에 있음)"
    found = detect_restrictions(description or "")
    if not found["restricted"]:
        return None
    record_channel(channel_id, channel_title, found["signals"], video_id=video_id)
    kinds = ", ".join(s["kind"] for s in found["signals"])
    return f"consent_required: 설명란 이용 제한 ({kinds})"
