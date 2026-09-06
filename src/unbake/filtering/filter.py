"""② 필터 — 싼 것부터 5단 필터 (기존 저장소에서 이식, 검증된 로직).

하드(이력/임베드/길이/라이브/이용제한) → 규칙(제목 블랙리스트) → 자막 확인
→ LLM 경량 판별(주입된 judge, 배치 1콜) → 스코어링 상위 N만 queued.

LLM·저장소 결합을 끊었다:
- 4단 판별은 `judge: Callable[[str], dict]`로 주입받는다 — 어댑터가 프롬프트 템플릿과
  JSON 추출을 소유하고, 이 모듈은 후보 목록 텍스트 블록만 만들어 넘긴다
- 상태 전이는 duck-typed `history.transition(...)`으로 주입받는다 (adapters/sqlite가 구현)
"""
import math
from collections.abc import Callable
from typing import Protocol

from ..adapters.youtube.discover import Candidate
from .licensing import check_candidate

MAX_DURATION_MS = 600_000
TITLE_BLACKLIST = ["먹방", "ASMR", "몰아보기", "모음", "TOP", "top10", "브이로그",
                   "vlog", "쇼핑", "언박싱", "리뷰", "맛집", "챌린지"]

# 필터 판정 결과 상태 — adapters/sqlite 상태 테이블의 값과 일치해야 한다
FILTERED_OUT = "filtered_out"
DEFERRED = "deferred"
QUEUED = "queued"


class FilterHistory(Protocol):
    """필터 결과를 이력에 남기는 계약 — adapters/sqlite의 transition이 원형."""

    def transition(self, video_id: str, new_state: str, *,
                   reason: str | None = None,
                   caption_status: str | None = None) -> None: ...


def hard_and_rule_filter(c: Candidate) -> tuple[bool, str]:
    """→ (통과 여부, 탈락 사유 코드)."""
    if c.live:
        return False, "not_vod"
    if not c.embeddable:
        return False, "not_embeddable"
    # 이용 제한을 명시한 채널은 사전 동의 전까지 통과시키지 않는다 (화이트리스트도 예외 없음).
    # 감지된 채널은 seeds/consent-required-channels.json에 근거와 함께 쌓인다.
    consent = check_candidate(c.channel_id, c.channel_title, c.description,
                              video_id=c.video_id)
    if consent:
        return False, consent
    if c.duration_ms <= 0 or c.duration_ms > MAX_DURATION_MS:
        return False, "too_long"
    if not c.from_whitelist:            # 화이트리스트 채널은 규칙 스킵
        low = c.title.lower()
        for word in TITLE_BLACKLIST:
            if word.lower() in low:
                return False, f"rule_blacklist:{word}"
    return True, ""


def check_captions(candidates: list[Candidate]) -> None:
    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi()
    for c in candidates:
        try:
            tlist = api.list(c.video_id)
            try:
                tlist.find_manually_created_transcript(["ko"])
                c.caption_status = "manual"
            except Exception:
                tlist.find_generated_transcript(["ko"])
                c.caption_status = "auto"
        except Exception:
            c.caption_status = "none"


def candidates_block(candidates: list[Candidate]) -> str:
    """judge에 넘길 후보 목록 텍스트 블록 — 한 줄에 한 후보.

    어댑터의 프롬프트 템플릿(<<CANDIDATES>> 치환)에 그대로 들어가는 형식이다.
    """
    lines = []
    for c in candidates:
        desc = c.description.replace("\n", " ")[:150]
        lines.append(f"- videoId: {c.video_id} | 제목: {c.title} | 채널: {c.channel_title}"
                     f" | 길이: {c.duration_ms // 1000}s | 설명: {desc}")
    return "\n".join(lines)


def llm_verdicts(candidates: list[Candidate],
                 judge: Callable[[str], dict]) -> dict[str, dict]:
    """전 후보를 배치 1콜로 판별 → {videoId: {isRecipe, isSingleDish, dishName, confidence}}.

    judge 계약: 후보 목록 텍스트 블록(candidates_block 형식)을 받아
    {"verdicts": [{videoId, isRecipe, isSingleDish, dishName, confidence, reason}]}를
    돌려준다. 프롬프트 구성·LLM 호출·JSON 추출은 어댑터 책임이다.
    """
    if not candidates:
        return {}
    result = judge(candidates_block(candidates))
    return {v["videoId"]: v for v in result.get("verdicts", [])}


def score(c: Candidate, verdict: dict) -> float:
    caption = {"manual": 2.0, "auto": 1.0}.get(c.caption_status, 0.0)
    whitelist = 2.0 if c.from_whitelist else 0.0
    views = math.log10(max(c.view_count, 1)) / 2      # 조회수 100만 ≈ 3점
    conf = float(verdict.get("confidence", 0)) * 3
    return round(caption + whitelist + views + conf, 2)


def run_filter(candidates: list[Candidate], *, judge: Callable[[str], dict],
               history: FilterHistory, top_n: int = 15,
               caption_checker: Callable[[list[Candidate]], None] | None = None
               ) -> list[dict]:
    """필터 실행 → 상위 N을 queued로. 반환: 통과 목록(스코어 포함, 내림차순).

    history의 생명주기(연결·close)는 호출자가 관리한다.
    """
    survivors: list[Candidate] = []
    for c in candidates:
        ok, reason = hard_and_rule_filter(c)
        if ok:
            survivors.append(c)
        else:
            history.transition(c.video_id, FILTERED_OUT, reason=reason)

    (caption_checker or check_captions)(survivors)
    verdicts = llm_verdicts(survivors, judge)

    scored: list[dict] = []
    for c in survivors:
        v = verdicts.get(c.video_id, {})
        if not v.get("isRecipe") or not v.get("isSingleDish"):
            history.transition(c.video_id, FILTERED_OUT,
                              reason=f"llm_rejected: {v.get('reason', '판별 실패')}")
            continue
        scored.append({
            "videoId": c.video_id, "title": c.title, "channel": c.channel_title,
            "durationMs": c.duration_ms, "caption": c.caption_status,
            "dishName": v.get("dishName") or c.dish_hint,
            "confidence": v.get("confidence"), "score": score(c, v),
            "source": c.source,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    for i, item in enumerate(scored):
        if i < top_n:
            history.transition(item["videoId"], QUEUED,
                              reason=f"score={item['score']} dish={item['dishName']}",
                              caption_status=item["caption"])
        else:
            history.transition(item["videoId"], DEFERRED,
                              reason=f"score={item['score']} (top_{top_n} 밖)")
    return scored[:top_n]
