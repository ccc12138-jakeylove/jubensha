import pytest

from jubensha.storage.events import EventStore
from jubensha.storage.streams import TurnStreams


def test_stream_recovery_marks_incomplete_turn_without_replaying_it(tmp_path):
    events = EventStore(tmp_path / "streams.db")
    streams = TurnStreams(events)
    assert streams.begin("g", "key", "seat_1", "hash")
    assert streams.append("g", "key", "node_start", {"node": "router"}) == 1
    assert not streams.begin("g", "key", "seat_1", "hash")
    with pytest.raises(ValueError, match="different turn"):
        streams.begin("g", "key", "seat_1", "changed")
    recovered = TurnStreams(events)
    assert recovered.status("g", "key") == "interrupted"
    assert recovered.after("g", "key", 0)[0]["kind"] == "node_start"


def test_stream_terminal_event_is_persisted_for_reconnect(tmp_path):
    events = EventStore(tmp_path / "streams.db")
    streams = TurnStreams(events)
    streams.begin("g", "key", "seat_1", "hash")
    streams.append("g", "key", "done", {"reply": "safe"})
    assert TurnStreams(events).status("g", "key") == "completed"
    assert streams.after("g", "key", 0)[0]["payload"]["reply"] == "safe"
