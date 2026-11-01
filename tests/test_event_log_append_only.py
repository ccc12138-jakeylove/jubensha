import sqlite3

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
