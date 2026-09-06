import pytest

from unbake.events import EVENT_SCHEMA_VERSION, list_events, record_event


def test_이벤트는_파일_하나씩_immutable(tmp_path):
    e1 = record_event(tmp_path, video_id="v1", event_type="APPROVED", data={"revisionId": "r1"})
    e2 = record_event(tmp_path, video_id="v2", event_type="REJECTED", actor="human")
    files = list((tmp_path / "quality-events").glob("*.json"))
    assert len(files) == 2
    assert e1 != e2

    events = list_events(tmp_path)
    assert [e["eventId"] for e in events] == [e1, e2] or [e["eventId"] for e in events] == [e2, e1]
    first = events[0]
    assert first["schemaVersion"] == EVENT_SCHEMA_VERSION
    assert first["createdAt"]


def test_videoId_필터(tmp_path):
    record_event(tmp_path, video_id="v1", event_type="APPROVED")
    record_event(tmp_path, video_id="v2", event_type="APPROVED")
    assert len(list_events(tmp_path, video_id="v1")) == 1


def test_알수없는_eventType은_거부(tmp_path):
    with pytest.raises(ValueError):
        record_event(tmp_path, video_id="v1", event_type="INVENTED")


def test_이벤트_없으면_빈_목록(tmp_path):
    assert list_events(tmp_path) == []
