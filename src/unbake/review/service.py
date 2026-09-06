"""검수 데이터 서비스 — store(pipeline.db)와 output/ 산출물을 조립한다.

읽기: 목록(list_items) · review bundle(get_bundle).
쓰기: revise(사람 수정 → 새 revision) · approve(지정 revision 승인) · reject.

원칙 (docs/architecture.md):
- 사람 수정은 기존 candidate.json을 절대 덮어쓰지 않는다 —
  `output/<videoId>/revisions/<revisionId>.json`에 새 파일로 쌓는다.
- publish는 승인된 revision(videos.approved_revision_id)만 참조한다.
- ID(stepId/subStepId/claimId…)는 코드가 위치 기반으로 결정적으로 부여하므로,
  bundle을 만들 때마다 재부여해도 evaluation.json의 참조와 항상 일치한다.
"""

import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from unbake.adapters.naembii.mapper import structure_candidate
from unbake.adapters.sqlite import store as S
from unbake.adapters.sqlite.store import Store
from unbake.evaluation.claims import generate_claims
from unbake.evaluation.ids import (
    assign_blind_ids,
    assign_candidate_ids,
    assign_description_fact_ids,
)
from unbake.evaluation.temporal import SUSPECT_TIOU_DEFAULT
from unbake.events import record_event
from unbake.models import (
    SCHEMA_VERSION,
    BlindExtraction,
    DescriptionFacts,
    RecipeCandidate,
)

# 목록 기본 정렬 — 검수 관점에서 급한 상태부터
STATE_ORDER = [
    S.PENDING_REVIEW, S.APPROVED, S.REJECTED,
    S.PUBLISH_FAILED, S.PUBLISHED_DEV, S.DUPLICATE, S.PROD_FAILED, S.PUBLISHED_PROD,
    S.EVALUATING, S.EVALUATION_FAILED, S.ANALYZING, S.ANALYZE_FAILED,
    S.QUEUED, S.DEFERRED, S.DISCOVERED, S.FILTERED_OUT,
]

# store에 이력이 없지만 output/ 산출물은 있는 영상 (예: CLI evaluate 단독 실행).
# 열람은 허용하되 상태 전이·revision 기록은 불가 — 유사 상태값으로 표시한다.
UNTRACKED = "untracked"

# 등록이 끝난 상태 — 사람 수정(revise)을 받지 않는다
_LOCKED_STATES = {S.PUBLISHED_DEV, S.PUBLISHED_PROD, S.DUPLICATE}


class ReviewError(Exception):
    """API로 그대로 나가는 오류 — HTTP status와 사유를 함께 담는다."""

    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _read_json(path: Path) -> Any | None:
    """산출물 파일 하나를 읽는다 — 없거나 깨졌으면 None (한 파일이 전체를 죽이지 않게)."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


logger = logging.getLogger(__name__)

# publisher 계약: RecipeCreateRequest dict → PublishResult (adapters.naembii.client 참조).
# 주입 가능하게 두는 이유 — 테스트 격리 + 다른 백엔드 교체 (docs/architecture.md)
Publisher = Callable[[dict], Any]


def _candidate_hash(candidate_dump: dict) -> str:
    payload = json.dumps(candidate_dump, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class ReviewService:
    def __init__(
        self,
        db_path: Path,
        output_dir: Path,
        dev_publisher: Publisher | None = None,
        prod_publisher: Publisher | None = None,
    ):
        self.db_path = Path(db_path)
        self.output_dir = Path(output_dir)
        self._dev_publisher = dev_publisher
        self._prod_publisher = prod_publisher

    def _publisher(self, env: str) -> Publisher:
        """미주입 시 Config에서 lazy 조립 — 시크릿 없으면 503으로 명확히 실패."""
        injected = self._dev_publisher if env == "dev" else self._prod_publisher
        if injected is not None:
            return injected

        from unbake.adapters.naembii.client import NaembiiClient, publish_and_verify
        from unbake.config import Config

        cfg = Config.load()
        host = cfg.dev_api_host if env == "dev" else cfg.prod_api_host
        secret = cfg.dev_admin_secret if env == "dev" else cfg.prod_admin_secret
        if not host or not secret:
            raise ReviewError(
                503, f".env에 {env} 백엔드 host/secret이 없어 등록할 수 없습니다"
            )
        client = NaembiiClient(host, secret)
        return lambda payload: publish_and_verify(client, payload)

    # ---- 경로 규약 ----
    # revision artifact_path는 output_dir 기준 상대 경로로 저장한다 (저장소 이동에 안전).
    # 다른 도구가 절대 경로로 기록했더라도 읽기는 둘 다 허용한다.

    def _resolve(self, artifact_path: str) -> Path:
        p = Path(artifact_path)
        return p if p.is_absolute() else self.output_dir / p

    def _candidate_path(self, video_id: str) -> Path:
        return self.output_dir / video_id / "candidate.json"

    def _latest_candidate(
        self, video_id: str, revisions: list
    ) -> tuple[dict | None, str | None]:
        """최신 revision의 candidate(없으면 원본 candidate.json)와 그 revisionId."""
        for rev in reversed(revisions):
            data = _read_json(self._resolve(rev["artifact_path"]))
            if data is not None:
                return data, rev["revision_id"]
        return _read_json(self._candidate_path(video_id)), None

    # ---- 목록 ----

    def list_items(self, state: str | None = None) -> list[dict]:
        """store 이력 + output 산출물 병합 목록. state 쿼리로 필터."""
        if state is not None and state != UNTRACKED and state not in S.ALL_STATES:
            raise ReviewError(400, f"알 수 없는 상태: {state}")

        store = Store(self.db_path)
        try:
            items: list[dict] = []
            seen: set[str] = set()
            wanted = [state] if state and state != UNTRACKED else STATE_ORDER
            if state != UNTRACKED:
                for st in wanted:
                    for row in store.list_by_state(st):
                        seen.add(row["video_id"])
                        items.append(self._item_from_row(store, row))
            else:
                # untracked만 원할 때도 store 등록분은 제외 대상으로 알아야 한다
                for st in STATE_ORDER:
                    seen.update(r["video_id"] for r in store.list_by_state(st))

            if state is None or state == UNTRACKED:
                items.extend(self._untracked_items(seen))
            return items
        finally:
            store.close()

    def _item_from_row(self, store: Store, row) -> dict:
        vid = row["video_id"]
        revisions = store.list_revisions(vid)
        candidate, _rid = self._latest_candidate(vid, revisions)
        evaluation = _read_json(self.output_dir / vid / "evaluation.json")
        return {
            "id": vid,
            "state": row["state"],
            "reason": row["reason"],
            "title": row["title"],
            "channelTitle": row["channel_title"],
            "durationMs": row["duration_ms"],
            "updatedAt": row["updated_at"],
            "devRecipeId": row["dev_recipe_id"],
            "prodRecipeId": row["prod_recipe_id"],
            "approvedRevisionId": row["approved_revision_id"],
            "tracked": True,
            "hasArtifacts": candidate is not None,
            "dishName": (candidate or {}).get("dishName"),
            "stepCount": len((candidate or {}).get("steps", [])),
            "summary": (evaluation or {}).get("summary"),
            "revisionCount": len(revisions),
        }

    def _untracked_items(self, seen: set[str]) -> list[dict]:
        items = []
        if not self.output_dir.exists():
            return items
        for d in sorted(self.output_dir.iterdir()):
            if d.name in seen or not (d / "candidate.json").exists():
                continue
            candidate = _read_json(d / "candidate.json")
            if candidate is None or "videoId" not in candidate:
                continue  # 레시피 산출물이 아닌 디렉터리 방어
            evaluation = _read_json(d / "evaluation.json")
            items.append({
                "id": d.name,
                "state": UNTRACKED,
                "reason": "pipeline.db에 이력이 없는 산출물 — 열람만 가능",
                "title": candidate.get("title") or "",
                "channelTitle": "",
                "durationMs": candidate.get("durationMs"),
                "updatedAt": None,
                "devRecipeId": None,
                "prodRecipeId": None,
                "approvedRevisionId": None,
                "tracked": False,
                "hasArtifacts": True,
                "dishName": candidate.get("dishName"),
                "stepCount": len(candidate.get("steps", [])),
                "summary": (evaluation or {}).get("summary"),
                "revisionCount": 0,
            })
        return items

    # ---- review bundle ----

    def get_bundle(self, video_id: str) -> dict:
        """{video, candidate, evaluation, revisions, schemaVersion} + 평가 컨텍스트."""
        store = Store(self.db_path)
        try:
            row = store.get(video_id)
            revisions = store.list_revisions(video_id) if row else []
        finally:
            store.close()

        original = _read_json(self._candidate_path(video_id))
        if row is None and original is None:
            raise ReviewError(404, f"영상을 찾을 수 없습니다: {video_id}")

        candidate_raw, candidate_rid = self._latest_candidate(video_id, revisions)
        candidate = None
        if candidate_raw is not None:
            # ID는 코드가 결정적으로 부여한다 — 편집·프리뷰 렌더의 기준점
            model = assign_candidate_ids(RecipeCandidate.model_validate(candidate_raw))
            candidate = model.dump()

        if row is not None:
            video = {
                "videoId": video_id,
                "state": row["state"],
                "reason": row["reason"],
                "title": row["title"],
                "channelId": row["channel_id"],
                "channelTitle": row["channel_title"],
                "durationMs": row["duration_ms"],
                "devRecipeId": row["dev_recipe_id"],
                "prodRecipeId": row["prod_recipe_id"],
                "approvedRevisionId": row["approved_revision_id"],
                "updatedAt": row["updated_at"],
                "tracked": True,
            }
        else:
            video = {
                "videoId": video_id,
                "state": UNTRACKED,
                "reason": "pipeline.db에 이력이 없는 산출물 — 열람만 가능",
                "title": (original or {}).get("title") or "",
                "channelId": "", "channelTitle": "",
                "durationMs": (original or {}).get("durationMs"),
                "devRecipeId": None, "prodRecipeId": None,
                "approvedRevisionId": None, "updatedAt": None,
                "tracked": False,
            }

        return {
            "schemaVersion": SCHEMA_VERSION,
            "video": video,
            "candidate": candidate,               # 최신 승인 대상 revision 또는 원본
            "candidateRevisionId": candidate_rid,  # None이면 원본 candidate.json
            "evaluation": _read_json(self.output_dir / video_id / "evaluation.json"),
            "revisions": [
                {
                    "revisionId": r["revision_id"],
                    "parentRevisionId": r["parent_revision_id"],
                    "source": r["source"],  # extraction | human_edit
                    "createdAt": r["created_at"],
                }
                for r in revisions
            ],
            "evaluationContext": self._evaluation_context(video_id, original),
        }

    def _evaluation_context(self, video_id: str, original: dict | None) -> dict | None:
        """평가 산출물이 참조하는 ID들을 사람이 읽을 텍스트로 되살리는 컨텍스트.

        evaluation.json은 평가 시점 candidate(원본) 기준이므로, claim·step 텍스트도
        원본에서 결정적으로 재생성한다 — 사람 수정 revision과 섞지 않는다.
        """
        if original is None:
            return None
        try:
            candidate = assign_candidate_ids(RecipeCandidate.model_validate(original))
        except ValueError:
            return None
        blind_raw = _read_json(self.output_dir / video_id / "blind.json")
        desc_raw = _read_json(self.output_dir / video_id / "description-facts.json")
        blind = assign_blind_ids(BlindExtraction.model_validate(blind_raw or {}))
        desc = assign_description_fact_ids(DescriptionFacts.model_validate(desc_raw or {}))
        return {
            "candidate": candidate.dump(),
            "claims": [c.dump() for c in generate_claims(candidate)],
            "blind": blind.dump(),
            "descriptionFacts": desc.dump(),
            "suspectTiou": SUSPECT_TIOU_DEFAULT,
        }

    # ---- 쓰기 ----

    def _require_tracked(self, store: Store, video_id: str):
        row = store.get(video_id)
        if row is None:
            raise ReviewError(
                404, f"pipeline.db에 등록되지 않은 영상입니다: {video_id} — 열람만 가능"
            )
        return row

    def revise(self, video_id: str, payload: Any) -> dict:
        """수정된 candidate를 새 revision으로 저장 — 원본은 절대 덮어쓰지 않는다."""
        if not isinstance(payload, dict) or not isinstance(payload.get("candidate"), dict):
            raise ReviewError(400, "body에 candidate 객체가 필요합니다")
        candidate = RecipeCandidate.model_validate(payload["candidate"])  # 스키마 검증
        if candidate.video_id != video_id:
            raise ReviewError(
                400, f"candidate.videoId({candidate.video_id})가 경로({video_id})와 다릅니다"
            )

        store = Store(self.db_path)
        try:
            row = self._require_tracked(store, video_id)
            if row["state"] in _LOCKED_STATES:
                raise ReviewError(409, "이미 등록된 레시피는 수정할 수 없습니다")
            revisions = store.list_revisions(video_id)
            parent = revisions[-1]["revision_id"] if revisions else None

            revision_id = f"rev-{uuid.uuid4().hex[:12]}"
            rel_path = f"{video_id}/revisions/{revision_id}.json"
            target = self.output_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(candidate.dump(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            store.add_revision(
                revision_id, video_id,
                artifact_path=rel_path, source="human_edit", parent_revision_id=parent,
            )
            before, _ = self._latest_candidate(video_id, revisions)
            record_event(
                self.output_dir,
                video_id=video_id,
                event_type="REVISED",
                data={
                    "revisionId": revision_id,
                    "parentRevisionId": parent,
                    "beforeHash": _candidate_hash(before) if before else None,
                    "afterHash": _candidate_hash(candidate.dump()),
                },
            )
            return {
                "ok": True,
                "revisionId": revision_id,
                "parentRevisionId": parent,
                "artifactPath": rel_path,
            }
        finally:
            store.close()

    def approve(self, video_id: str, revision_id: str | None = None) -> dict:
        """지정(기본: 최신) revision 승인 — approved_revision_id 기록 + 상태 전이."""
        store = Store(self.db_path)
        try:
            self._require_tracked(store, video_id)
            revisions = store.list_revisions(video_id)

            if revision_id is not None:
                rev = store.get_revision(revision_id)
                if rev is None or rev["video_id"] != video_id:
                    raise ReviewError(400, f"이 영상의 revision이 아닙니다: {revision_id}")
            elif revisions:
                revision_id = revisions[-1]["revision_id"]
            else:
                # revision 이력이 없으면 원본 candidate.json을 extraction revision으로
                # 등록해 승인한다 — publish는 항상 revision만 참조해야 하므로 (§3.6)
                if not self._candidate_path(video_id).exists():
                    raise ReviewError(409, "승인할 candidate 산출물이 없습니다")
                revision_id = f"rev-{video_id}-orig"
                if store.get_revision(revision_id) is None:
                    store.add_revision(
                        revision_id, video_id,
                        artifact_path=f"{video_id}/candidate.json", source="extraction",
                    )

            store.transition(video_id, S.APPROVED)  # 위반 시 InvalidTransition → 409
            store.set_approved_revision(video_id, revision_id)
            record_event(
                self.output_dir,
                video_id=video_id,
                event_type="APPROVED",
                data={"revisionId": revision_id},
            )
            return {"ok": True, "state": S.APPROVED, "approvedRevisionId": revision_id}
        finally:
            store.close()

    def reject(self, video_id: str, reason: str = "") -> dict:
        store = Store(self.db_path)
        try:
            self._require_tracked(store, video_id)
            reason = reason.strip() or "사유 미기재"
            store.transition(video_id, S.REJECTED, reason=reason)
            record_event(
                self.output_dir, video_id=video_id, event_type="REJECTED", data={"reason": reason}
            )
            return {"ok": True, "state": S.REJECTED}
        finally:
            store.close()

    # ---- 등록 (사람이 대시보드 버튼으로만 호출한다 — 자동 등록 경로 없음) ----

    def _approved_payload(self, store: Store, video_id: str) -> tuple[dict, str]:
        """승인된 revision → RecipeCreateRequest dict. (payload, revisionId) 반환."""
        row = self._require_tracked(store, video_id)
        revision_id = row["approved_revision_id"]
        if not revision_id:
            raise ReviewError(409, "승인된 revision이 없습니다 — 먼저 approve 하세요")
        rev = store.get_revision(revision_id)
        if rev is None:
            raise ReviewError(500, f"승인된 revision 기록이 없습니다: {revision_id}")
        data = _read_json(self._resolve(rev["artifact_path"]))
        if data is None:
            raise ReviewError(500, f"revision artifact를 읽지 못했습니다: {rev['artifact_path']}")
        candidate = RecipeCandidate.model_validate(data)
        meta = _read_json(self.output_dir / video_id / "meta.json")

        result = structure_candidate(candidate, meta)
        if result.request is None:
            raise ReviewError(
                409, "하드 규칙 위반 — 등록 불가: " + " / ".join(result.errors)[:400]
            )
        for warning in result.warnings:
            logger.warning("[%s] %s", video_id, warning)
        return result.request.model_dump(exclude_none=True), revision_id

    def publish_dev(self, video_id: str) -> dict:
        """승인된 revision을 dev 백엔드에 등록. 409(중복)는 성공 취급 (멱등)."""
        store = Store(self.db_path)
        try:
            payload, revision_id = self._approved_payload(store, video_id)
            outcome = self._publisher("dev")(payload)

            if outcome.status == "created":
                store.transition(video_id, S.PUBLISHED_DEV, dev_recipe_id=outcome.recipe_id)
            elif outcome.status == "duplicate":
                store.transition(video_id, S.DUPLICATE, reason="dev에 이미 등록된 영상 (409)")
            else:
                store.transition(
                    video_id, S.PUBLISH_FAILED,
                    reason=f"{outcome.error_code}: {outcome.message}"[:300],
                )
                raise ReviewError(502, f"dev 등록 실패 — {outcome.error_code}: {outcome.message}")

            record_event(
                self.output_dir,
                video_id=video_id,
                event_type="PUBLISHED",
                data={
                    "env": "dev",
                    "status": outcome.status,
                    "recipeId": outcome.recipe_id,
                    "revisionId": revision_id,
                },
            )
            return {
                "ok": True,
                "state": store.get(video_id)["state"],
                "status": outcome.status,
                "recipeId": outcome.recipe_id,
            }
        finally:
            store.close()

    def promote(self, video_id: str) -> dict:
        """dev 검증이 끝난 레시피를 prod에 등록 — 마지막 게이트, 사람 버튼 전용."""
        store = Store(self.db_path)
        try:
            row = self._require_tracked(store, video_id)
            if row["state"] != S.PUBLISHED_DEV:
                raise ReviewError(
                    409, f"prod 등록은 published_dev 상태에서만 가능합니다 (현재: {row['state']})"
                )
            payload, revision_id = self._approved_payload(store, video_id)
            outcome = self._publisher("prod")(payload)

            if outcome.status == "created":
                store.transition(video_id, S.PUBLISHED_PROD, prod_recipe_id=outcome.recipe_id)
            elif outcome.status == "duplicate":
                # prod에 이미 있으면 목적 달성 — 성공 취급 (멱등)
                store.transition(video_id, S.PUBLISHED_PROD, reason="prod에 이미 등록 (409)")
            else:
                store.transition(
                    video_id, S.PROD_FAILED,
                    reason=f"{outcome.error_code}: {outcome.message}"[:300],
                )
                raise ReviewError(502, f"prod 등록 실패 — {outcome.error_code}: {outcome.message}")

            record_event(
                self.output_dir,
                video_id=video_id,
                event_type="PUBLISHED",
                data={
                    "env": "prod",
                    "status": outcome.status,
                    "recipeId": outcome.recipe_id,
                    "revisionId": revision_id,
                },
            )
            return {
                "ok": True,
                "state": S.PUBLISHED_PROD,
                "status": outcome.status,
                "recipeId": outcome.recipe_id,
            }
        finally:
            store.close()
