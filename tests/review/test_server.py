"""검수 서버 http 통합 테스트 — 목록/번들/revise/approve/reject + 스텁·오류 경로."""

from copy import deepcopy

from tests.review.conftest import CANDIDATE, VID, VID2, VID3
from unbake.adapters.sqlite import store as S
from unbake.adapters.sqlite.store import Store

# ---- GET /api/items ----


def test_items_merges_store_and_output(api):
    status, items = api("GET", "/api/items")
    assert status == 200
    by_id = {it["id"]: it for it in items}
    assert set(by_id) == {VID, VID2, VID3}

    main = by_id[VID]
    assert main["state"] == "pending_review"
    assert main["tracked"] is True
    assert main["hasArtifacts"] is True
    assert main["dishName"] == "애호박볶음"
    assert main["stepCount"] == 2
    assert main["revisionCount"] == 1
    assert main["summary"]["sourceConflictCount"] == 1  # 평가 summary 병합

    # store 이력이 없는 산출물은 untracked로 노출된다 (열람만)
    assert by_id[VID3]["state"] == "untracked"
    assert by_id[VID3]["tracked"] is False


def test_items_state_filter(api):
    status, items = api("GET", "/api/items?state=pending_review")
    assert status == 200
    assert {it["id"] for it in items} == {VID, VID2}

    status, items = api("GET", "/api/items?state=approved")
    assert (status, items) == (200, [])

    status, body = api("GET", "/api/items?state=nope")
    assert status == 400
    assert body["ok"] is False


# ---- GET /api/items/<videoId> (review bundle) ----


def test_bundle_shape(api):
    status, bundle = api("GET", f"/api/items/{VID}")
    assert status == 200
    assert bundle["schemaVersion"] == "1.0.0"
    assert bundle["video"]["state"] == "pending_review"
    assert bundle["video"]["durationMs"] == 60000

    # candidate: 최신 revision(여기선 extraction 원본) + 코드가 부여한 계층 ID
    assert bundle["candidateRevisionId"] == "rev-ext-001"
    steps = bundle["candidate"]["steps"]
    assert steps[0]["stepId"] == "s1"
    assert steps[0]["subSteps"][0]["subStepId"] == "s1a"
    assert bundle["candidate"]["ingredients"][0]["ingredientId"] == "i1"

    # 평가 산출물 + revision 체인 요약
    assert bundle["evaluation"]["summary"]["matchedStepCount"] == 2
    assert [r["revisionId"] for r in bundle["revisions"]] == ["rev-ext-001"]
    assert bundle["revisions"][0]["source"] == "extraction"

    # 평가 컨텍스트 — claim 문장·fact/action ID를 사람이 읽을 수 있게 되살린다
    ctx = bundle["evaluationContext"]
    claims = {c["claimId"]: c for c in ctx["claims"]}
    assert claims["c1"]["text"].startswith("재료 '애호박'")
    assert ctx["blind"]["actions"][0]["actionId"] == "a1"
    assert ctx["descriptionFacts"]["facts"][0]["factId"] == "d1"
    assert ctx["suspectTiou"] == 0.3


def test_bundle_unknown_video_is_404(api):
    status, body = api("GET", "/api/items/nope00000000")
    assert status == 404
    assert body["ok"] is False


# ---- POST /api/items/<videoId>/revise ----


def _edited_candidate(vid=VID):
    edited = deepcopy(CANDIDATE)
    edited["videoId"] = vid
    edited["dishName"] = "애호박 소금볶음"
    edited["steps"][0]["subSteps"][0]["text"] = "애호박을 얇게 채 썬다"
    return edited


def test_revise_creates_new_revision_and_keeps_original(api, workspace):
    original_bytes = (workspace["output_dir"] / VID / "candidate.json").read_bytes()

    status, out = api("POST", f"/api/items/{VID}/revise", {"candidate": _edited_candidate()})
    assert status == 200
    assert out["ok"] is True
    rid = out["revisionId"]
    assert rid.startswith("rev-")
    assert out["parentRevisionId"] == "rev-ext-001"  # 체인이 이어진다

    # 원본 candidate.json은 1바이트도 바뀌지 않는다 (덮어쓰기 금지)
    assert (workspace["output_dir"] / VID / "candidate.json").read_bytes() == original_bytes
    # 새 revision 파일이 revisions/ 아래 생긴다
    assert (workspace["output_dir"] / VID / "revisions" / f"{rid}.json").exists()

    store = Store(workspace["db_path"])
    revs = store.list_revisions(VID)
    store.close()
    assert [r["source"] for r in revs] == ["extraction", "human_edit"]
    assert revs[-1]["revision_id"] == rid

    # bundle의 candidate가 최신 revision으로 바뀐다
    _, bundle = api("GET", f"/api/items/{VID}")
    assert bundle["candidateRevisionId"] == rid
    assert bundle["candidate"]["dishName"] == "애호박 소금볶음"
    assert len(bundle["revisions"]) == 2
    # 평가 컨텍스트는 평가 시점(원본) 기준을 유지한다
    assert bundle["evaluationContext"]["candidate"]["dishName"] == "애호박볶음"


def test_revise_rejects_bad_input(api):
    # videoId 불일치
    status, body = api("POST", f"/api/items/{VID}/revise", {"candidate": _edited_candidate(VID2)})
    assert status == 400 and body["ok"] is False

    # 스키마 위반 (dishName 누락)
    broken = _edited_candidate()
    del broken["dishName"]
    status, body = api("POST", f"/api/items/{VID}/revise", {"candidate": broken})
    assert status == 400 and "스키마" in body["reason"]

    # candidate 없음
    status, body = api("POST", f"/api/items/{VID}/revise", {})
    assert status == 400

    # untracked 영상은 수정 불가
    status, body = api("POST", f"/api/items/{VID3}/revise", {"candidate": _edited_candidate(VID3)})
    assert status == 404


# ---- POST /api/items/<videoId>/approve ----


def test_approve_targets_latest_revision(api, workspace):
    _, out = api("POST", f"/api/items/{VID}/revise", {"candidate": _edited_candidate()})
    rid = out["revisionId"]

    status, out = api("POST", f"/api/items/{VID}/approve", {})
    assert status == 200
    assert out == {"ok": True, "state": "approved", "approvedRevisionId": rid}

    store = Store(workspace["db_path"])
    row = store.get(VID)
    store.close()
    assert row["state"] == S.APPROVED
    assert row["approved_revision_id"] == rid

    # 이미 approved → 재승인은 상태 전이 위반 (409)
    status, body = api("POST", f"/api/items/{VID}/approve", {})
    assert status == 409 and body["ok"] is False


def test_approve_without_revision_registers_original(api, workspace):
    """revision 이력이 없으면 원본 candidate.json을 extraction revision으로 승인한다."""
    status, out = api("POST", f"/api/items/{VID2}/approve", {})
    assert status == 200
    assert out["approvedRevisionId"] == f"rev-{VID2}-orig"

    store = Store(workspace["db_path"])
    rev = store.get_revision(f"rev-{VID2}-orig")
    row = store.get(VID2)
    store.close()
    assert rev["source"] == "extraction"
    assert rev["artifact_path"] == f"{VID2}/candidate.json"
    assert row["state"] == S.APPROVED


def test_approve_explicit_revision_must_belong_to_video(api):
    status, body = api("POST", f"/api/items/{VID2}/approve", {"revisionId": "rev-ext-001"})
    assert status == 400 and body["ok"] is False


# ---- POST /api/items/<videoId>/reject ----


def test_reject_transitions_with_reason(api, workspace):
    status, out = api("POST", f"/api/items/{VID}/reject", {"reason": "2단계 구간이 어긋남"})
    assert status == 200
    assert out == {"ok": True, "state": "rejected"}

    store = Store(workspace["db_path"])
    row = store.get(VID)
    store.close()
    assert row["state"] == S.REJECTED
    assert row["reason"] == "2단계 구간이 어긋남"

    # 반려 후 재승인 경로는 열려 있다 (rejected → approved)
    status, out = api("POST", f"/api/items/{VID}/approve", {})
    assert status == 200 and out["state"] == "approved"


# ---- 등록 스텁 + 라우팅 ----


def test_publish_endpoints_routed(api):
    # 배선 완료 — 승인 전이므로 409 (라우팅·상태 검증이 살아 있는지 확인)
    for action, expected in (("publish-dev", "승인된 revision"), ("promote", "published_dev")):
        status, body = api("POST", f"/api/items/{VID}/{action}", {})
        assert status == 409
        assert expected in body["reason"]


def test_unknown_routes(api):
    status, _ = api("GET", "/api/nope")
    assert status == 404
    status, _ = api("POST", f"/api/items/{VID}/explode", {})
    assert status == 404
