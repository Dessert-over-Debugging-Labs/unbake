"""공용 유틸 — LLM 출력 JSON 추출, 유튜브 URL 파싱, 다양성 선정 (기존 저장소에서 이식)."""
import json
import re


class JsonExtractionError(ValueError):
    """LLM 최종 출력에서 JSON 오브젝트를 찾지 못했을 때."""


def extract_json(text: str) -> dict:
    """LLM 최종 출력에서 JSON 오브젝트 추출 (```json 펜스/서두 문장 허용)."""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise JsonExtractionError(f"출력에서 JSON을 찾지 못함: {text[:300]}")
    return json.loads(text[start:end + 1])


def parse_video_id(text: str) -> str | None:
    """유튜브 URL·ID에서 videoId 추출 (watch·youtu.be·shorts·embed·live, 순수 ID)."""
    t = (text or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", t):
        return t
    patterns = [
        r"[?&]v=([A-Za-z0-9_-]{11})",
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"/shorts/([A-Za-z0-9_-]{11})",
        r"/embed/([A-Za-z0-9_-]{11})",
        r"/live/([A-Za-z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, t)
        if m:
            return m.group(1)
    return None


SHORT_MS, MID_MS = 60_000, 240_000   # 길이 버킷: 초단편 / 중편 / 장편


def _bucket(ms: int) -> str:
    if ms <= SHORT_MS:
        return "short"
    return "mid" if ms <= MID_MS else "long"


def select_diverse(cands: list[dict], n: int) -> list[dict]:
    """배치 선정 — 채널·요리명 중복 회피, 길이 버킷 분산, 수동 자막 1건 우선.

    스코어에서 중복 페널티를 빼고 매번 최고점을 고르는 그리디.
    """
    picked: list[dict] = []
    pool = list(cands)
    while pool and len(picked) < n:
        chans = {p.get("channel") for p in picked}
        dishes = {p.get("dishName") for p in picked}
        buckets = {_bucket(p.get("durationMs") or 0) for p in picked}
        has_manual = any(p.get("caption") == "manual" for p in picked)

        def key(c: dict, *, chans=chans, dishes=dishes,
                buckets=buckets, has_manual=has_manual) -> float:
            v = float(c.get("score") or 0)
            if c.get("channel") in chans:
                v -= 3
            if c.get("dishName") and c.get("dishName") in dishes:
                v -= 3
            if _bucket(c.get("durationMs") or 0) in buckets:
                v -= 1
            if not has_manual and c.get("caption") == "manual":
                v += 2
            return v

        best = max(pool, key=key)
        pool.remove(best)
        picked.append(best)
    return picked
