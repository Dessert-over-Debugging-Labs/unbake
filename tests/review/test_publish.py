"""등록 배선 — 승인 revision → structure → publisher → 상태 전이 + quality event."""

import pytest

from tests.review.conftest import VID
from unbake.adapters.naembii.client import PublishResult
from unbake.events import list_events
from unbake.review.service import ReviewError, ReviewService


class FakePublisher:
    def __init__(self, *results: PublishResult):
        self.results = list(results)
        self.payloads: list[dict] = []

    def __call__(self, payload: dict) -> PublishResult:
        self.payloads.append(payload)
        return self.results.pop(0)


def _service(workspace, dev=None, prod=None) -> ReviewService:
    return ReviewService(
        workspace["db_path"], workspace["output_dir"], dev_publisher=dev, prod_publisher=prod
    )


def _approve(service):
    return service.approve(VID)


def test_승인_전_등록은_409(workspace):
    service = _service(workspace, dev=FakePublisher())
    with pytest.raises(ReviewError) as err:
        service.publish_dev(VID)
    assert err.value.status == 409


def test_dev_등록_성공(workspace):
    dev = FakePublisher(PublishResult(status="created", recipe_id="42"))
    service = _service(workspace, dev=dev)
    _approve(service)

    out = service.publish_dev(VID)
    assert out["ok"] is True and out["status"] == "created" and out["recipeId"] == "42"
    assert out["state"] == "published_dev"

    # payload는 승인 revision을 구조화한 것 — 결정적 후처리 흔적 확인
    payload = dev.payloads[0]
    assert payload["video"]["platformVideoId"] == VID
    assert payload["steps"][0]["videoEndMs"] == 20_400  # 딱 붙은 경계 +400ms 패딩

    # quality event: APPROVED + PUBLISHED(dev)
    types = [(e["eventType"], e["data"].get("env")) for e in
             list_events(workspace["output_dir"], video_id=VID)]
    assert ("APPROVED", None) in types
    assert ("PUBLISHED", "dev") in types


def test_dev_중복은_성공_취급(workspace):
    dev = FakePublisher(PublishResult(status="duplicate", error_code="DUP"))
    service = _service(workspace, dev=dev)
    _approve(service)
    out = service.publish_dev(VID)
    assert out["ok"] is True and out["state"] == "duplicate"


def test_dev_실패는_상태_기록_후_502(workspace):
    dev = FakePublisher(PublishResult(status="failed", error_code="X", message="boom"))
    service = _service(workspace, dev=dev)
    _approve(service)
    with pytest.raises(ReviewError) as err:
        service.publish_dev(VID)
    assert err.value.status == 502

    from unbake.adapters.sqlite.store import Store

    store = Store(workspace["db_path"])
    try:
        assert store.get(VID)["state"] == "publish_failed"
    finally:
        store.close()


def test_prod_등록은_published_dev에서만(workspace):
    service = _service(workspace, prod=FakePublisher())
    _approve(service)
    with pytest.raises(ReviewError) as err:
        service.promote(VID)
    assert err.value.status == 409


def test_prod_등록_성공(workspace):
    dev = FakePublisher(PublishResult(status="created", recipe_id="42"))
    prod = FakePublisher(PublishResult(status="created", recipe_id="7"))
    service = _service(workspace, dev=dev, prod=prod)
    _approve(service)
    service.publish_dev(VID)

    out = service.promote(VID)
    assert out["state"] == "published_prod" and out["recipeId"] == "7"
    types = [(e["eventType"], e["data"].get("env")) for e in
             list_events(workspace["output_dir"], video_id=VID)]
    assert ("PUBLISHED", "prod") in types


def test_시크릿_없으면_503(workspace, monkeypatch):
    monkeypatch.delenv("NAEMBII_DEV_ADMIN_SECRET", raising=False)
    service = _service(workspace)  # publisher 미주입 → Config 조립 시도
    _approve(service)
    with pytest.raises(ReviewError) as err:
        service.publish_dev(VID)
    assert err.value.status == 503
