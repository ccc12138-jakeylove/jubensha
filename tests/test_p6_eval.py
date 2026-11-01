import pytest

from jubensha.eval.invariants import check_invariants
from jubensha.eval.metrics import cohen_kappa
from jubensha.eval.simulator import PERSONAS, simulate_game
from jubensha.schema.events import EventType, GameEvent
from jubensha.engine.fsm import Phase
from jubensha.storage.events import EventStore


def test_four_personas_complete(script, tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    store = EventStore(tmp_path / "eval.db")
    results = [simulate_game(script, store, persona) for persona in PERSONAS]
    assert all(result.completed and not result.errors for result in results)
    assert all(not result.invariant_failures for result in results)
    assert all(result.proactive_count >= 2 for result in results)


def test_invariant_gate_catches_duplicate_clue(script):
    event = GameEvent(seq=1, game_id="g", actor_seat_id="seat_1", turn=1,
                      phase=Phase.SEARCH, type=EventType.CLUE_FOUND,
                      payload={"clue_id": "C01", "location_id": "room_302", "search_cost": 1},
                      visible_to=["*"])
    failures = check_invariants(script, [event, event.model_copy(update={"seq": 2})])
    assert any("duplicate clue" in failure for failure in failures)


def test_kappa_requires_paired_labels():
    assert cohen_kappa([0, 1, 0, 1], [0, 1, 0, 1]) == 1
    with pytest.raises(ValueError):
        cohen_kappa([0], [])
