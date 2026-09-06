"""검수 서버 통합 테스트 fixture — 임시 dir에 산출물 + store를 만들고 실제 HTTP로 검증."""

import json
import threading
import urllib.error
import urllib.request
from copy import deepcopy

import pytest

from unbake.adapters.sqlite import store as S
from unbake.adapters.sqlite.store import Store
from unbake.review.server import make_server
from unbake.review.service import ReviewService

# 검수 대기 + revision 이력 보유 (기본 시나리오)
VID = "abc123def45"
# 검수 대기 + revision 이력 없음 (원본 승인 시나리오)
VID2 = "zzz999zzz99"
# store 이력 없이 output/만 존재 (untracked)
VID3 = "untracked0aa"

CANDIDATE = {
    "videoId": VID,
    "durationMs": 60000,
    "dishName": "애호박볶음",
    "title": "초간단 애호박볶음",
    "summary": "10분 반찬",
    "servings": "2인분",
    "cookTimeMin": 10,
    "difficulty": "EASY",
    "ingredients": [
        {"group": "MAIN", "name": "애호박", "amount": "1개"},
        {"group": "SEASONING", "name": "소금", "amount": "1작은술"},
    ],
    "steps": [
        {
            "title": "손질",
            "startMs": 0,
            "endMs": 20000,
            "subSteps": [{"text": "애호박을 채 썬다"}, {"text": "소금 1작은술을 뿌려 절인다"}],
        },
        {
            "title": "볶기",
            "startMs": 20000,
            "endMs": 45000,
            "subSteps": [{"text": "팬에 볶는다"}],
        },
    ],
    "tags": [{"name": "반찬"}],
}

BLIND = {
    "audioFacts": [
        {"kind": "AMOUNT", "text": "소금은 한 작은술", "name": "소금", "amount": "1작은술"}
    ],
    "visualFacts": [],
    "actions": [
        {"description": "애호박을 썬다", "startMs": 0, "endMs": 10000},
        {"description": "팬에서 볶는다", "startMs": 21000, "endMs": 40000},
    ],
}

DESCRIPTION_FACTS = {
    "facts": [{"kind": "INGREDIENT", "text": "애호박 1개", "name": "애호박", "amount": "1개"}]
}

EVALUATION = {
    "evaluationRunId": "run-test-0001",
    "videoId": VID,
    "claimEvaluations": [
        {
            "claimId": "c1",
            "bySource": {
                "DESCRIPTION": {"claimId": "c1", "verdict": "SUPPORTED", "factRefs": ["d1"]},
                "AUDIO": {"claimId": "c1", "verdict": "UNKNOWN", "factRefs": []},
                "VISUAL": {"claimId": "c1", "verdict": "UNKNOWN", "factRefs": []},
            },
            "fused": "SUPPORTED",
        },
        {
            "claimId": "c4",
            "bySource": {
                "DESCRIPTION": {"claimId": "c4", "verdict": "UNKNOWN", "factRefs": []},
                "AUDIO": {
                    "claimId": "c4", "verdict": "CONTRADICTED",
                    "factRefs": ["au1"], "observedValue": "2작은술",
                },
                "VISUAL": {"claimId": "c4", "verdict": "SUPPORTED", "factRefs": []},
            },
            "fused": "CONFLICT",
            "severity": "MAJOR",
        },
    ],
    "subStepMappings": [
        {"subStepId": "s1a", "status": "MATCHED", "actionIds": ["a1"]},
        {"subStepId": "s1b", "status": "UNOBSERVABLE"},
        {"subStepId": "s2a", "status": "MATCHED", "actionIds": ["a2"]},
    ],
    "stepRollups": [
        {"stepId": "s1", "status": "MATCHED", "matchedCount": 1, "unobservableCount": 1},
        {"stepId": "s2", "status": "MATCHED", "matchedCount": 1},
    ],
    "temporalEvaluations": [
        {
            "stepId": "s1", "matched": True,
            "candidateStartMs": 0, "candidateEndMs": 20000,
            "actionSpanStartMs": 0, "actionSpanEndMs": 10000,
            "intersectionMs": 10000, "unionMs": 20000, "temporalIou": 0.5,
            "startDeltaMs": 0, "endDeltaMs": 10000,
        },
        {
            "stepId": "s2", "matched": True,
            "candidateStartMs": 20000, "candidateEndMs": 45000,
            "actionSpanStartMs": 21000, "actionSpanEndMs": 40000,
            "intersectionMs": 19000, "unionMs": 25000, "temporalIou": 0.76,
            "startDeltaMs": -1000, "endDeltaMs": 5000,
        },
    ],
    "detectedOmissions": [
        {"source": "AUDIO", "kind": "TIP", "text": "마늘을 곁들이면 좋다", "factRefs": ["au1"]}
    ],
    "validationIssues": [],
    "summary": {
        "contradictionCount": 0,
        "sourceConflictCount": 1,
        "unknownClaimCount": 0,
        "matchedStepCount": 2,
        "unobservableSubStepCount": 1,
        "suspectSegmentCount": 0,
        "unverifiedSegmentCount": 0,
        "medianTemporalIou": 0.63,
        "omissionCount": 1,
    },
}

MANIFEST = {
    "evaluationRunId": "run-test-0001",
    "schemaVersion": "1.0.0",
    "inputHash": "deadbeef",
    "createdAt": "2026-09-05T00:00:00+00:00",
    "calls": [],
}


def _write_artifacts(output_dir, vid, *, full=True):
    """output/<vid>/ 아래 산출물 파일을 만든다."""
    target = output_dir / vid
    target.mkdir(parents=True)
    candidate = deepcopy(CANDIDATE)
    candidate["videoId"] = vid
    files = {"candidate.json": candidate}
    if full:
        evaluation = deepcopy(EVALUATION)
        evaluation["videoId"] = vid
        files |= {
            "blind.json": BLIND,
            "description-facts.json": DESCRIPTION_FACTS,
            "evaluation.json": evaluation,
            "manifest.json": MANIFEST,
        }
    for name, data in files.items():
        (target / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def workspace(tmp_path):
    """산출물 3종 + pipeline.db — VID(이력+revision), VID2(이력만), VID3(untracked)."""
    output_dir = tmp_path / "output"
    db_path = tmp_path / "pipeline.db"
    _write_artifacts(output_dir, VID)
    _write_artifacts(output_dir, VID2, full=False)
    _write_artifacts(output_dir, VID3, full=False)

    store = Store(db_path)
    for vid, title in [(VID, "초간단 애호박볶음"), (VID2, "김치찌개 황금레시피")]:
        store.discover(vid, title=title, channel_title="채널A", duration_ms=60000)
        for state in [S.QUEUED, S.ANALYZING, S.EVALUATING, S.PENDING_REVIEW]:
            store.transition(vid, state)
    store.add_revision(
        "rev-ext-001", VID, artifact_path=f"{VID}/candidate.json", source="extraction"
    )
    store.close()
    return {"db_path": db_path, "output_dir": output_dir}


@pytest.fixture
def server(workspace):
    """임시 포트에 실제 ThreadingHTTPServer를 띄운다 — http 레벨 통합 검증."""
    service = ReviewService(workspace["db_path"], workspace["output_dir"])
    httpd = make_server(service, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


@pytest.fixture
def api(server):
    """(status, json) 을 돌려주는 최소 HTTP 클라이언트."""

    def call(method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            server + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    return call
