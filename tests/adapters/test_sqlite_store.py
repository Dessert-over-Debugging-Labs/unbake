import sqlite3

import pytest

from unbake.adapters.sqlite import store as S
from unbake.adapters.sqlite.store import InvalidTransition, Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


def test_discover_and_duplicate(store):
    assert store.discover("vid1", title="테스트", source="search:김치찌개") is True
    assert store.discover("vid1") is False  # 중복은 False
    row = store.get("vid1")
    assert row["state"] == S.DISCOVERED
    assert row["source"] == "search:김치찌개"


def test_happy_path_to_prod(store):
    store.discover("vid1")
    for state in [S.QUEUED, S.ANALYZING, S.EVALUATING, S.PENDING_REVIEW, S.APPROVED]:
        store.transition("vid1", state)
    store.transition("vid1", S.PUBLISHED_DEV, dev_recipe_id="dev-123")
    store.transition("vid1", S.PUBLISHED_PROD, prod_recipe_id="prod-456")
    row = store.get("vid1")
    assert row["state"] == S.PUBLISHED_PROD
    assert row["dev_recipe_id"] == "dev-123"
    assert row["prod_recipe_id"] == "prod-456"


def test_invalid_transition_raises(store):
    store.discover("vid1")
    with pytest.raises(InvalidTransition):
        store.transition("vid1", S.PUBLISHED_PROD)  # discovered에서 바로 prod 불가


def test_analyzing_cannot_skip_evaluation(store):
    """④평가를 건너뛰는 analyzing → pending_review 직행은 금지 (2026-09-05)."""
    store.discover("vid1")
    store.transition("vid1", S.QUEUED)
    store.transition("vid1", S.ANALYZING)
    with pytest.raises(InvalidTransition):
        store.transition("vid1", S.PENDING_REVIEW)


def test_evaluation_retry_and_reject_paths(store):
    """evaluating ↔ evaluation_failed 재시도, 반복 실패 시 rejected 탈락."""
    store.discover("vid1")
    for state in [S.QUEUED, S.ANALYZING, S.EVALUATING]:
        store.transition("vid1", state)
    store.transition("vid1", S.EVALUATION_FAILED, reason="파싱 실패")
    store.transition("vid1", S.EVALUATING)          # 재평가
    store.transition("vid1", S.EVALUATION_FAILED, reason="반복 실패")
    store.transition("vid1", S.REJECTED, reason="평가 불가 판정")
    assert store.get("vid1")["state"] == S.REJECTED


def test_terminal_states_locked(store):
    store.discover("vid1")
    store.transition("vid1", S.FILTERED_OUT, reason="not_embeddable")
    with pytest.raises(InvalidTransition):
        store.transition("vid1", S.QUEUED)


def test_retry_paths(store):
    store.discover("vid1")
    for state in [S.QUEUED, S.ANALYZING, S.EVALUATING, S.PENDING_REVIEW, S.APPROVED]:
        store.transition("vid1", state)
    store.transition("vid1", S.PUBLISH_FAILED, reason="500")
    store.transition("vid1", S.APPROVED)  # 재시도 복귀
    store.transition("vid1", S.PUBLISHED_DEV)
    store.transition("vid1", S.PROD_FAILED, reason="네트워크")
    store.transition("vid1", S.PUBLISHED_DEV)  # 재시도 복귀
    assert store.get("vid1")["state"] == S.PUBLISHED_DEV


def test_counts_and_list(store):
    store.discover("a")
    store.discover("b")
    store.transition("b", S.FILTERED_OUT, reason="too_long")
    assert store.counts() == {S.DISCOVERED: 1, S.FILTERED_OUT: 1}
    assert [r["video_id"] for r in store.list_by_state(S.FILTERED_OUT)] == ["b"]


def test_collect_failure_from_queued(store):
    """수집 실패 시 queued에서 바로 탈락 처리 (재시도 루프 방지)."""
    store.discover("vid1")
    store.transition("vid1", S.QUEUED)
    store.transition("vid1", S.ANALYZE_FAILED, reason="다운로드 실패")
    assert store.get("vid1")["state"] == S.ANALYZE_FAILED


# ---- revision (docs/architecture.md) ----


def test_revision_chain_and_approval(store):
    """추출본 → 사람 수정 revision 체인, 승인 revision은 videos에 기록."""
    store.discover("vid1")
    store.add_revision("rev-1", "vid1", artifact_path="output/vid1/rev-1.json")
    store.add_revision("rev-2", "vid1", source="human_edit",
                       parent_revision_id="rev-1",
                       artifact_path="output/vid1/rev-2.json")
    chain = store.revision_chain("rev-2")
    assert [r["revision_id"] for r in chain] == ["rev-1", "rev-2"]
    assert chain[0]["source"] == "extraction" and chain[0]["parent_revision_id"] is None
    assert chain[1]["source"] == "human_edit"

    store.set_approved_revision("vid1", "rev-2")
    assert store.get("vid1")["approved_revision_id"] == "rev-2"
    assert [r["revision_id"] for r in store.list_revisions("vid1")] == ["rev-1", "rev-2"]


def test_revision_guards(store):
    store.discover("vid1")
    with pytest.raises(ValueError):        # 알 수 없는 source
        store.add_revision("rev-x", "vid1", source="llm_edit", artifact_path="p")
    with pytest.raises(KeyError):          # 없는 영상
        store.add_revision("rev-x", "ghost", artifact_path="p")
    with pytest.raises(KeyError):          # 없는 부모
        store.add_revision("rev-x", "vid1", parent_revision_id="ghost", artifact_path="p")
    with pytest.raises(KeyError):          # 없는 revision 승인 불가
        store.set_approved_revision("vid1", "ghost")


def test_approved_revision_must_belong_to_video(store):
    store.discover("vid1")
    store.discover("vid2")
    store.add_revision("rev-1", "vid1", artifact_path="p")
    with pytest.raises(ValueError):
        store.set_approved_revision("vid2", "rev-1")  # 남의 revision 승인 금지


# ---- evaluation run (docs/architecture.md) ----


def test_run_lifecycle(store):
    """pending → running → failed → (attempt 증가) running → succeeded."""
    store.discover("vid1")
    store.add_revision("rev-1", "vid1", artifact_path="p")
    store.create_run("run-1", "vid1", "rev-1", input_hash="abc123")
    row = store.get_run("run-1")
    assert row["status"] == S.RUN_PENDING and row["attempt"] == 0
    assert row["input_hash"] == "abc123"

    store.transition_run("run-1", S.RUN_RUNNING)
    store.transition_run("run-1", S.RUN_FAILED)
    assert store.bump_run_attempt("run-1") == 1     # 재시도 기록
    store.transition_run("run-1", S.RUN_RUNNING)
    store.transition_run("run-1", S.RUN_SUCCEEDED,
                         artifact_path="output/vid1/run-1.json",
                         manifest_json='{"model": "gemini-2.5-flash"}')
    row = store.get_run("run-1")
    assert row["status"] == S.RUN_SUCCEEDED
    assert row["artifact_path"] == "output/vid1/run-1.json"
    assert row["manifest_json"] == '{"model": "gemini-2.5-flash"}'


def test_run_invalid_transitions(store):
    store.discover("vid1")
    store.add_revision("rev-1", "vid1", artifact_path="p")
    store.create_run("run-1", "vid1", "rev-1", input_hash="h")
    with pytest.raises(InvalidTransition):
        store.transition_run("run-1", S.RUN_SUCCEEDED)  # pending에서 바로 성공 불가
    store.transition_run("run-1", S.RUN_RUNNING)
    store.transition_run("run-1", S.RUN_SUCCEEDED)
    with pytest.raises(InvalidTransition):
        store.transition_run("run-1", S.RUN_RUNNING)    # succeeded는 종결


def test_run_guards_and_listing(store):
    store.discover("vid1")
    store.add_revision("rev-1", "vid1", artifact_path="p")
    with pytest.raises(KeyError):
        store.create_run("run-x", "ghost", "rev-1", input_hash="h")
    with pytest.raises(KeyError):
        store.create_run("run-x", "vid1", "ghost", input_hash="h")
    store.create_run("run-1", "vid1", "rev-1", input_hash="h1")
    store.create_run("run-2", "vid1", "rev-1", input_hash="h2")
    assert [r["run_id"] for r in store.list_runs(video_id="vid1")] == ["run-1", "run-2"]
    assert [r["run_id"] for r in store.list_runs(revision_id="rev-1")] == ["run-1", "run-2"]


def test_migration_adds_new_columns(tmp_path):
    """구버전 DB(새 컬럼 없음)를 열면 경량 마이그레이션이 컬럼을 추가한다."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE videos (
            video_id TEXT PRIMARY KEY, state TEXT NOT NULL, reason TEXT,
            title TEXT, channel_id TEXT, channel_title TEXT, duration_ms INTEGER,
            source TEXT, dish_hint TEXT, dev_recipe_id TEXT, prod_recipe_id TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    s = Store(db)
    cols = {r[1] for r in s.conn.execute("PRAGMA table_info(videos)")}
    assert "caption_status" in cols and "approved_revision_id" in cols
    s.close()
