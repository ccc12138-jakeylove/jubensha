import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from jubensha.engine.fsm import Phase
from jubensha.schema.events import EventType, GameEvent
from jubensha.storage.events import EventStore


def test_event_log_append_only(tmp_path):
    path = tmp_path / "game.db"
    store = EventStore(path)
    store.create_game("g", "s", "A1")
    original = [store.append(GameEvent(seq=0, game_id="g", actor_seat_id="seat_1", turn=i,
                                       phase=Phase.ENTRY, type=EventType.PLAYER_INPUT,
                                       payload={"text": str(i)}, visible_to=["*"])) for i in (1, 2)]
    with store.connect() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE game_events SET event_json='{}' WHERE game_id='g'")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM game_events WHERE game_id='g'")
    loaded = EventStore(path).events("g")
    assert [e.seq for e in loaded] == [1, 2]
    assert loaded == original


def test_concurrent_appends_keep_contiguous_sequence(tmp_path):
    store = EventStore(tmp_path / "game.db")
    store.create_game("g", "s", "A1")
    def append(index):
        return store.append(GameEvent(seq=0, game_id="g", actor_seat_id="seat_1",
                                      turn=index, phase=Phase.ACT_OPEN,
                                      type=EventType.PLAYER_INPUT,
                                      payload={"text": str(index)}, visible_to=["*"]))
    with ThreadPoolExecutor(max_workers=8) as pool:
        saved = list(pool.map(append, range(40)))
    assert sorted(event.seq for event in saved) == list(range(1, 41))
    assert [event.seq for event in store.events("g")] == list(range(1, 41))
