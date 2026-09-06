"""① 탐색 — YouTube Data API 2-트랙 수집 (기존 저장소에서 이식, 검증된 로직).

트랙 A: 요리명 사전 × 수식어 검색 (search.list, 100 unit/호출)
트랙 B: 채널 화이트리스트 업로드 순회 (playlistItems.list, 1 unit) + 과거 백필 커서
공통: videos.list로 상세(길이·임베드·조회수) 확보 → 이력에 discovered로 등록

쿼터 절약 3종:
  1. 이력에 있는 영상은 videos.list 조회 전에 컷 (백필이 과거를 반복해 훑기 때문)
  2. playlistItems.list 50개/1 unit 페이지 최대 활용 (검색 100 unit 대비 사실상 공짜)
  3. 업로드 재생목록 id는 커서에 캐시 — channels.list 재조회 없음

저장소 결합을 끊기 위해 sqlite를 직접 열지 않는다. 커서·이력은 duck-typed
인터페이스(`CursorStore` / `DiscoveryHistory`)로 주입받는다 — adapters/sqlite가
같은 메서드를 구현해 꽂히고, 테스트·단발 실행은 `InMemoryCursorStore`로 충분하다.
"""
import json
import random
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import requests

# 저장소 루트의 seeds/ — 테스트는 이 모듈 변수를 monkeypatch한다
SEEDS_DIR = Path(__file__).resolve().parents[4] / "seeds"
API = "https://www.googleapis.com/youtube/v3"


def _iso_to_ms(duration: str) -> int:
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return ((h * 60 + mi) * 60 + s) * 1000


@dataclass
class Candidate:
    video_id: str
    title: str = ""
    channel_id: str = ""
    channel_title: str = ""
    duration_ms: int = 0
    embeddable: bool = True
    live: bool = False
    view_count: int = 0
    description: str = ""
    source: str = ""            # search:<키워드> | channel:<id>
    dish_hint: str = ""
    from_whitelist: bool = False
    caption_status: str = "unknown"   # ②에서 채움


class CursorStore(Protocol):
    """트랙 B 백필 커서 저장소 계약 — adapters/sqlite의 channel_cursor 테이블이 원형.

    row는 Mapping 접근(`row["page_token"]`)을 지원해야 한다 (sqlite3.Row·dict 모두 OK).
    """

    def channel_cursor(self, channel_id: str) -> Mapping | None: ...

    def save_channel_cursor(self, channel_id: str, *, uploads_playlist: str = "",
                            page_token: str | None = None,
                            exhausted: bool = False) -> None: ...


class DiscoveryHistory(Protocol):
    """탐색 이력 계약 — get은 미지의 영상이면 None, discover는 신규 등록 시 참."""

    def get(self, video_id: str) -> Mapping | None: ...

    def discover(self, video_id: str, *, title: str = "", channel_id: str = "",
                 channel_title: str = "", duration_ms: int = 0,
                 source: str = "", dish_hint: str = "") -> bool: ...


class InMemoryCursorStore:
    """sqlite 없이 쓰는 커서 저장소 — 프로세스 생명주기 한정 (테스트·단발 실행용).

    row 형태(exhausted는 0/1 정수)를 sqlite adapter와 동일하게 맞춘다.
    """

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}

    def channel_cursor(self, channel_id: str) -> dict | None:
        return self._rows.get(channel_id)

    def save_channel_cursor(self, channel_id: str, *, uploads_playlist: str = "",
                            page_token: str | None = None,
                            exhausted: bool = False) -> None:
        self._rows[channel_id] = {
            "channel_id": channel_id, "uploads_playlist": uploads_playlist,
            "page_token": page_token, "exhausted": 1 if exhausted else 0,
        }

    def reset_channel_cursor(self, channel_id: str) -> None:
        row = self._rows.get(channel_id)
        if row:
            row["page_token"] = None
            row["exhausted"] = 0


def _get(api_key: str, path: str, **params) -> dict:
    params["key"] = api_key
    res = requests.get(f"{API}/{path}", params=params, timeout=15)
    res.raise_for_status()
    return res.json()


def search_track(api_key: str, n_searches: int, rng: random.Random,
                 max_per_search: int = 10) -> list[Candidate]:
    seeds = json.loads((SEEDS_DIR / "dishes.json").read_text(encoding="utf-8"))
    dishes = rng.sample(seeds["dishes"], min(n_searches, len(seeds["dishes"])))
    out: list[Candidate] = []
    for dish in dishes:
        modifier = rng.choice(seeds["modifiers"])
        q = f"{dish} {modifier}"
        data = _get(api_key, "search", part="snippet", q=q, type="video",
                    regionCode="KR", relevanceLanguage="ko", maxResults=max_per_search)
        for it in data.get("items", []):
            out.append(Candidate(
                video_id=it["id"]["videoId"],
                source=f"search:{q}", dish_hint=dish))
    return out


PAGE_SIZE = 50            # playlistItems.list 최대치 (1 unit / 호출)
BACKFILL_PAGES = 3        # 실행당 채널별로 거슬러 올라갈 페이지 수


def _playlist_page(api_key: str, uploads: str, token: str | None) -> dict:
    params = dict(part="snippet", playlistId=uploads, maxResults=PAGE_SIZE)
    if token:
        params["pageToken"] = token
    return _get(api_key, "playlistItems", **params)


def channel_track(api_key: str, cursors: CursorStore, *,
                  backfill_pages: int = BACKFILL_PAGES) -> list[Candidate]:
    """화이트리스트 채널의 업로드를 **최신 + 과거 백필**로 수집 (2026-08-07 개선).

    이전 구현은 매 실행 최신 10개만 다시 훑어서, 한 번 이력에 들어간 뒤로는 그 채널에서
    새 영상이 올라오기 전까지 아무것도 나오지 않았다 — 좋은 과거 영상이 영영 도달 불가였다.

    이제 두 갈래로 돈다.
      1. 헤드 1페이지 — 신규 업로드 포착 (매 실행)
      2. 백필 N페이지 — 저장된 커서에서 과거로 계속 (회차가 쌓이면 카탈로그 전체에 도달)

    playlistItems.list는 1 unit/50개라 검색(100 unit/회) 대비 사실상 공짜다.
    커서는 주입받은 CursorStore에 남아 실행 간 이어진다. 끝까지 훑은 채널은
    exhausted로 표시해 헤드만 확인한다.
    """
    seeds = json.loads((SEEDS_DIR / "channels.json").read_text(encoding="utf-8"))
    out: list[Candidate] = []
    for ch in seeds["channels"]:
        cid = ch["channelId"]
        row = cursors.channel_cursor(cid)
        uploads = (row["uploads_playlist"] if row else "") or ""
        if not uploads:
            data = _get(api_key, "channels", part="contentDetails", id=cid)
            items = data.get("items", [])
            if not items:
                continue
            uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        def add(page: dict, cid: str = cid) -> None:
            for it in page.get("items", []):
                vid = it["snippet"].get("resourceId", {}).get("videoId")
                if vid:
                    out.append(Candidate(video_id=vid, source=f"channel:{cid}",
                                         from_whitelist=True))

        # 1. 헤드 — 신규 업로드
        add(_playlist_page(api_key, uploads, None))

        # 2. 백필 — 커서에서 과거로
        token = (row["page_token"] if row else None)
        exhausted = bool(row["exhausted"]) if row else False
        if not exhausted:
            for _ in range(max(0, backfill_pages)):
                page = _playlist_page(api_key, uploads, token)
                add(page)
                token = page.get("nextPageToken")
                if not token:
                    exhausted = True     # 카탈로그 끝 — 다음 실행부터는 헤드만
                    break
        cursors.save_channel_cursor(cid, uploads_playlist=uploads,
                                    page_token=token, exhausted=exhausted)
    return out


def enrich(api_key: str, candidates: list[Candidate]) -> list[Candidate]:
    """videos.list 배치로 상세 확보 (50개/1 unit)."""
    by_id = {c.video_id: c for c in candidates}          # videoId dedupe
    ids = list(by_id.keys())
    for i in range(0, len(ids), 50):
        data = _get(api_key, "videos", part="snippet,contentDetails,statistics,status",
                    id=",".join(ids[i:i + 50]))
        for it in data.get("items", []):
            c = by_id[it["id"]]
            sn, cd, st = it["snippet"], it["contentDetails"], it["status"]
            c.title = sn.get("title", "")
            c.channel_id = sn.get("channelId", "")
            c.channel_title = sn.get("channelTitle", "")
            c.description = (sn.get("description") or "")[:500]
            c.live = sn.get("liveBroadcastContent", "none") != "none"
            c.duration_ms = _iso_to_ms(cd.get("duration", ""))
            c.embeddable = st.get("embeddable", True)
            c.view_count = int(it.get("statistics", {}).get("viewCount", 0))
    return list(by_id.values())


def _round_robin(items: list[Candidate]) -> list[Candidate]:
    """source(채널·검색어)별로 한 편씩 번갈아 뽑아 재배열한다.

    후보 목록은 소스별로 뭉쳐 들어온다(채널1 200편 → 채널2 200편 …). 그대로 앞에서
    잘라내면 첫 소스가 정원을 통째로 가져간다 — 실제로 트랙 B 등록이 1분요리 뚝딱이형
    한 채널로만 32건 쏠렸다.
    """
    groups: dict[str, list[Candidate]] = {}
    for c in items:
        groups.setdefault(c.source, []).append(c)
    out: list[Candidate] = []
    i = 0
    while True:
        added = False
        for g in groups.values():
            if i < len(g):
                out.append(g[i])
                added = True
        if not added:
            return out
        i += 1


# 트랙 B(화이트리스트) 예약 지분 — 검색 결과가 target을 다 먹어버리지 않게 한다.
# 백필로 후보가 늘어난 뒤에는 이 보장이 없으면 트랙 B가 등록에 도달하지 못한다.
WHITELIST_SHARE = 0.5


def discover(api_key: str, history: DiscoveryHistory, cursors: CursorStore, *,
             n_searches: int = 5, seed: int | None = None,
             target: int = 50) -> list[Candidate]:
    """탐색 실행 → 신규 후보를 이력에 discovered로 등록하고 반환.

    history·cursors의 생명주기(연결·close)는 호출자가 관리한다.
    """
    rng = random.Random(seed)
    candidates = search_track(api_key, n_searches, rng) + channel_track(api_key, cursors)

    # 이미 이력에 있는 영상은 상세 조회 전에 걸러낸다 (videos.list 할당량 절약).
    # 백필은 과거를 반복해 훑으므로 이 컷이 없으면 매번 같은 영상을 다시 조회한다.
    seen: set = set()
    unknown: list[Candidate] = []
    for c in candidates:
        if c.video_id in seen:
            continue
        seen.add(c.video_id)
        if history.get(c.video_id) is None:
            unknown.append(c)

    enriched = {c.video_id: c for c in enrich(api_key, unknown)}
    # source(채널·키워드)별 라운드로빈 — 앞쪽 채널이 정원을 독식하지 않게 한다.
    # 백필로 채널당 후보가 200편씩 쌓이면서 실제로 1번 채널이 트랙 B 정원을 다 먹었다.
    wl = _round_robin([enriched[c.video_id] for c in unknown if c.from_whitelist])
    sr = _round_robin([enriched[c.video_id] for c in unknown if not c.from_whitelist])

    # 트랙 B 예약분 → 트랙 A → 남는 자리는 남은 쪽에서 채운다
    wl_quota = int(target * WHITELIST_SHARE)
    picked = wl[:wl_quota] + sr[:target - min(len(wl), wl_quota)]
    if len(picked) < target:
        rest = wl[wl_quota:] + sr[target - min(len(wl), wl_quota):]
        picked += rest[:target - len(picked)]

    fresh: list[Candidate] = []
    for c in picked:
        if history.discover(c.video_id, title=c.title, channel_id=c.channel_id,
                            channel_title=c.channel_title, duration_ms=c.duration_ms,
                            source=c.source, dish_hint=c.dish_hint):
            fresh.append(c)
    return fresh
