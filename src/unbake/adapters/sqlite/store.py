"""처리 이력 저장소 — SQLite 단일 파일, workflow 상태 머신의 구현.

모든 단계(②중복 컷, ⑥검수, ⑦멱등 재시도, ①채널 승격 판단)가 이 이력에 의존한다.

상태 접합 2층 구조 (docs/architecture.md):
- workflow 상태: videos.state — analyzing → evaluating → pending_review → …
- evaluation run: evaluation_runs — pending/running/succeeded/failed + attempt + artifact
검수 수정은 덮어쓰지 않고 revisions에 새 revision으로 쌓고(§3.6), publish는
videos.approved_revision_id로 승인된 revision만 참조한다.
"""
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

# 상태 정의 (docs/architecture.md — 기존 14상태 + evaluating 확장)
DISCOVERED = "discovered"
FILTERED_OUT = "filtered_out"
DEFERRED = "deferred"
QUEUED = "queued"
ANALYZING = "analyzing"
ANALYZE_FAILED = "analyze_failed"
EVALUATING = "evaluating"
EVALUATION_FAILED = "evaluation_failed"
PENDING_REVIEW = "pending_review"
REJECTED = "rejected"
APPROVED = "approved"
PUBLISH_FAILED = "publish_failed"
DUPLICATE = "duplicate"
PUBLISHED_DEV = "published_dev"
PROD_FAILED = "prod_failed"
PUBLISHED_PROD = "published_prod"

ALL_STATES = {
    DISCOVERED, FILTERED_OUT, DEFERRED, QUEUED, ANALYZING, ANALYZE_FAILED,
    EVALUATING, EVALUATION_FAILED, PENDING_REVIEW, REJECTED, APPROVED,
    PUBLISH_FAILED, DUPLICATE, PUBLISHED_DEV, PROD_FAILED, PUBLISHED_PROD,
}

# 허용 전이 — 위반은 파이프라인 버그이므로 즉시 에러
TRANSITIONS: dict[str, set] = {
    DISCOVERED: {FILTERED_OUT, DEFERRED, QUEUED},
    DEFERRED: {FILTERED_OUT, QUEUED},
    # 수집 실패는 분석 전에도 탈락 처리 / filtered_out 은 영상 호출 전 도메인 게이트 탈락
    QUEUED: {ANALYZING, ANALYZE_FAILED, FILTERED_OUT},
    ANALYZING: {ANALYZE_FAILED, EVALUATING},   # ④평가를 거치지 않는 직행은 없다
    EVALUATING: {EVALUATION_FAILED, PENDING_REVIEW},
    EVALUATION_FAILED: {EVALUATING, REJECTED},     # 재평가 또는 탈락
    PENDING_REVIEW: {REJECTED, APPROVED},
    REJECTED: {APPROVED, PENDING_REVIEW},          # 재검수 허용
    APPROVED: {PUBLISH_FAILED, DUPLICATE, PUBLISHED_DEV},
    PUBLISH_FAILED: {APPROVED},                     # 재시도
    PUBLISHED_DEV: {PUBLISHED_PROD, PROD_FAILED},
    PROD_FAILED: {PUBLISHED_DEV},                   # 재시도
    # FILTERED_OUT / ANALYZE_FAILED / DUPLICATE / PUBLISHED_PROD 는 종결 상태
}

# revision 출처 (docs/architecture.md — 검수 수정은 덮어쓰지 않고 새 revision)
REVISION_SOURCES = {"extraction", "human_edit"}

# evaluation run 상태 (docs/architecture.md)
RUN_PENDING = "pending"
RUN_RUNNING = "running"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"

RUN_STATES = {RUN_PENDING, RUN_RUNNING, RUN_SUCCEEDED, RUN_FAILED}

RUN_TRANSITIONS: dict[str, set] = {
    RUN_PENDING: {RUN_RUNNING},
    RUN_RUNNING: {RUN_SUCCEEDED, RUN_FAILED},
    RUN_FAILED: {RUN_RUNNING},              # 재시도 (attempt 증가와 함께)
    # RUN_SUCCEEDED 는 종결 상태
}


class InvalidTransition(Exception):
    pass


class Store:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                video_id      TEXT PRIMARY KEY,
                state         TEXT NOT NULL,
                reason        TEXT,
                title         TEXT,
                channel_id    TEXT,
                channel_title TEXT,
                duration_ms   INTEGER,
                source        TEXT,            -- 수집 경로: search:<키워드> | channel:<id> | manual
                dish_hint     TEXT,
                dev_recipe_id  TEXT,
                prod_recipe_id TEXT,
                approved_revision_id TEXT,     -- 검수 승인된 revision (publish는 이것만 참조)
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS channel_cursor (
                channel_id       TEXT PRIMARY KEY,
                uploads_playlist TEXT,           -- 업로드 재생목록 id (채널당 고정 — 재조회 절약)
                page_token       TEXT,           -- 다음 백필 시작 지점 (NULL이면 처음부터)
                exhausted        INTEGER DEFAULT 0,  -- 과거 끝까지 훑었나
                updated_at       TEXT NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS revisions (
                revision_id        TEXT PRIMARY KEY,
                video_id           TEXT NOT NULL,
                parent_revision_id TEXT,             -- NULL이면 최초 추출본
                source             TEXT NOT NULL,    -- extraction | human_edit
                artifact_path      TEXT NOT NULL,    -- RecipeCandidate snapshot 파일
                created_at         TEXT NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS evaluation_runs (
                run_id        TEXT PRIMARY KEY,
                video_id      TEXT NOT NULL,
                revision_id   TEXT NOT NULL,
                status        TEXT NOT NULL,     -- pending | running | succeeded | failed
                attempt       INTEGER NOT NULL DEFAULT 0,
                input_hash    TEXT NOT NULL,     -- 입력 snapshot hash (재현성 §3.6)
                artifact_path TEXT,              -- 평가 산출물 (성공 시)
                manifest_json TEXT,              -- 모델 ID·프롬프트 버전·usage·재시도 이력
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
        """)
        # 경량 마이그레이션 — 기존 DB에 컬럼 추가
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(videos)")}
        if "caption_status" not in cols:
            self.conn.execute("ALTER TABLE videos ADD COLUMN caption_status TEXT")
        if "approved_revision_id" not in cols:
            self.conn.execute("ALTER TABLE videos ADD COLUMN approved_revision_id TEXT")
        self.conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def discover(self, video_id: str, *, title: str = "", channel_id: str = "",
                 channel_title: str = "", duration_ms: int = 0,
                 source: str = "manual", dish_hint: str = "") -> bool:
        """신규 영상 등록. 이미 있으면 False (중복 컷은 호출부에서 이 반환값으로 판단)."""
        if self.get(video_id) is not None:
            return False
        now = self._now()
        self.conn.execute(
            "INSERT INTO videos (video_id, state, title, channel_id, channel_title,"
            " duration_ms, source, dish_hint, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (video_id, DISCOVERED, title, channel_id, channel_title,
             duration_ms, source, dish_hint, now, now))
        self.conn.commit()
        return True

    # ---- ① 트랙 B 백필 커서 ----
    # 화이트리스트 채널의 업로드 목록을 회차마다 조금씩 거슬러 올라가기 위한 상태.
    # 이게 없으면 매 실행이 최신 페이지만 다시 훑어 과거 영상에 영영 도달하지 못한다.

    def channel_cursor(self, channel_id: str) -> sqlite3.Row | None:
        cur = self.conn.execute(
            "SELECT * FROM channel_cursor WHERE channel_id=?", (channel_id,))
        return cur.fetchone()

    def save_channel_cursor(self, channel_id: str, *, uploads_playlist: str = "",
                            page_token: str | None = None,
                            exhausted: bool = False) -> None:
        self.conn.execute(
            "INSERT INTO channel_cursor"
            " (channel_id, uploads_playlist, page_token, exhausted, updated_at)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(channel_id) DO UPDATE SET"
            "  uploads_playlist=excluded.uploads_playlist,"
            "  page_token=excluded.page_token,"
            "  exhausted=excluded.exhausted,"
            "  updated_at=excluded.updated_at",
            (channel_id, uploads_playlist, page_token, 1 if exhausted else 0, self._now()))
        self.conn.commit()

    def reset_channel_cursor(self, channel_id: str) -> None:
        """백필을 처음부터 다시 — 채널이 과거 영상을 추가·공개 전환한 경우용."""
        self.conn.execute(
            "UPDATE channel_cursor SET page_token=NULL, exhausted=0, updated_at=?"
            " WHERE channel_id=?", (self._now(), channel_id))
        self.conn.commit()

    def get(self, video_id: str) -> sqlite3.Row | None:
        cur = self.conn.execute("SELECT * FROM videos WHERE video_id=?", (video_id,))
        return cur.fetchone()

    def transition(self, video_id: str, new_state: str, *, reason: str | None = None,
                   dev_recipe_id: str | None = None,
                   prod_recipe_id: str | None = None,
                   caption_status: str | None = None) -> None:
        if new_state not in ALL_STATES:
            raise ValueError(f"unknown state: {new_state}")
        row = self.get(video_id)
        if row is None:
            raise KeyError(f"video not found: {video_id}")
        allowed = TRANSITIONS.get(row["state"], set())
        if new_state not in allowed:
            raise InvalidTransition(f"{row['state']} -> {new_state} ({video_id})")
        sets = ["state=?", "reason=?", "updated_at=?"]
        args: list = [new_state, reason, self._now()]
        if dev_recipe_id is not None:
            sets.append("dev_recipe_id=?")
            args.append(dev_recipe_id)
        if prod_recipe_id is not None:
            sets.append("prod_recipe_id=?")
            args.append(prod_recipe_id)
        if caption_status is not None:
            sets.append("caption_status=?")
            args.append(caption_status)
        args.append(video_id)
        self.conn.execute(f"UPDATE videos SET {', '.join(sets)} WHERE video_id=?", args)
        self.conn.commit()

    def list_by_state(self, state: str) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM videos WHERE state=? ORDER BY updated_at DESC", (state,))
        return cur.fetchall()

    def counts(self) -> dict[str, int]:
        cur = self.conn.execute("SELECT state, COUNT(*) AS c FROM videos GROUP BY state")
        return {r["state"]: r["c"] for r in cur.fetchall()}

    # ---- revision (docs/architecture.md) ----
    # 검수 수정은 덮어쓰지 않고 새 revision으로 쌓는다. publish는 승인된 revision만.

    def add_revision(self, revision_id: str, video_id: str, *, artifact_path: str,
                     source: str = "extraction",
                     parent_revision_id: str | None = None) -> None:
        if source not in REVISION_SOURCES:
            raise ValueError(f"unknown revision source: {source}")
        if self.get(video_id) is None:
            raise KeyError(f"video not found: {video_id}")
        if parent_revision_id is not None and self.get_revision(parent_revision_id) is None:
            raise KeyError(f"parent revision not found: {parent_revision_id}")
        self.conn.execute(
            "INSERT INTO revisions (revision_id, video_id, parent_revision_id,"
            " source, artifact_path, created_at) VALUES (?,?,?,?,?,?)",
            (revision_id, video_id, parent_revision_id, source, artifact_path, self._now()))
        self.conn.commit()

    def get_revision(self, revision_id: str) -> sqlite3.Row | None:
        cur = self.conn.execute(
            "SELECT * FROM revisions WHERE revision_id=?", (revision_id,))
        return cur.fetchone()

    def list_revisions(self, video_id: str) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM revisions WHERE video_id=? ORDER BY created_at, revision_id",
            (video_id,))
        return cur.fetchall()

    def revision_chain(self, revision_id: str) -> list[sqlite3.Row]:
        """부모 체인을 최초 추출본 → 해당 revision 순으로 반환."""
        chain: list[sqlite3.Row] = []
        seen: set = set()
        cur_id: str | None = revision_id
        while cur_id is not None:
            if cur_id in seen:      # 순환은 데이터 손상 — 조용히 돌지 않는다
                raise RuntimeError(f"revision cycle detected: {cur_id}")
            seen.add(cur_id)
            row = self.get_revision(cur_id)
            if row is None:
                raise KeyError(f"revision not found: {cur_id}")
            chain.append(row)
            cur_id = row["parent_revision_id"]
        chain.reverse()
        return chain

    def set_approved_revision(self, video_id: str, revision_id: str) -> None:
        """검수 승인된 revision 기록 — publish는 이 revision만 참조한다."""
        rev = self.get_revision(revision_id)
        if rev is None:
            raise KeyError(f"revision not found: {revision_id}")
        if rev["video_id"] != video_id:
            raise ValueError(
                f"revision {revision_id}는 video {rev['video_id']} 소속 — {video_id} 아님")
        self.conn.execute(
            "UPDATE videos SET approved_revision_id=?, updated_at=? WHERE video_id=?",
            (revision_id, self._now(), video_id))
        self.conn.commit()

    # ---- evaluation run (docs/architecture.md) ----
    # workflow 상태(evaluating)와 별개의 2층 — 실행 자체는 항상 추적한다.

    def create_run(self, run_id: str, video_id: str, revision_id: str, *,
                   input_hash: str) -> None:
        if self.get(video_id) is None:
            raise KeyError(f"video not found: {video_id}")
        if self.get_revision(revision_id) is None:
            raise KeyError(f"revision not found: {revision_id}")
        now = self._now()
        self.conn.execute(
            "INSERT INTO evaluation_runs (run_id, video_id, revision_id, status,"
            " attempt, input_hash, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, video_id, revision_id, RUN_PENDING, 0, input_hash, now, now))
        self.conn.commit()

    def get_run(self, run_id: str) -> sqlite3.Row | None:
        cur = self.conn.execute(
            "SELECT * FROM evaluation_runs WHERE run_id=?", (run_id,))
        return cur.fetchone()

    def list_runs(self, *, video_id: str | None = None,
                  revision_id: str | None = None) -> list[sqlite3.Row]:
        conds, args = [], []
        if video_id is not None:
            conds.append("video_id=?")
            args.append(video_id)
        if revision_id is not None:
            conds.append("revision_id=?")
            args.append(revision_id)
        where = f" WHERE {' AND '.join(conds)}" if conds else ""
        cur = self.conn.execute(
            f"SELECT * FROM evaluation_runs{where} ORDER BY created_at, run_id", args)
        return cur.fetchall()

    def transition_run(self, run_id: str, new_status: str, *,
                       artifact_path: str | None = None,
                       manifest_json: str | None = None) -> None:
        if new_status not in RUN_STATES:
            raise ValueError(f"unknown run status: {new_status}")
        row = self.get_run(run_id)
        if row is None:
            raise KeyError(f"run not found: {run_id}")
        allowed = RUN_TRANSITIONS.get(row["status"], set())
        if new_status not in allowed:
            raise InvalidTransition(f"run {row['status']} -> {new_status} ({run_id})")
        sets = ["status=?", "updated_at=?"]
        args: list = [new_status, self._now()]
        if artifact_path is not None:
            sets.append("artifact_path=?")
            args.append(artifact_path)
        if manifest_json is not None:
            sets.append("manifest_json=?")
            args.append(manifest_json)
        args.append(run_id)
        self.conn.execute(
            f"UPDATE evaluation_runs SET {', '.join(sets)} WHERE run_id=?", args)
        self.conn.commit()

    def bump_run_attempt(self, run_id: str) -> int:
        """재시도 시 attempt 증가 — 모든 시도를 기록한다(§3.5). 증가 후 값을 반환."""
        row = self.get_run(run_id)
        if row is None:
            raise KeyError(f"run not found: {run_id}")
        new_attempt = row["attempt"] + 1
        self.conn.execute(
            "UPDATE evaluation_runs SET attempt=?, updated_at=? WHERE run_id=?",
            (new_attempt, self._now(), run_id))
        self.conn.commit()
        return new_attempt

    def close(self) -> None:
        self.conn.close()
