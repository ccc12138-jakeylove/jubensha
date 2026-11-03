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
    assert all(result.judgment_outcomes for result in results)
    assert all(result.attributions for result in results if not result.win)


def test_invariant_gate_catches_duplicate_clue(script):
    event = GameEvent(seq=1, game_id="g", actor_seat_id="seat_1", turn=1,
                      phase=Phase.SEARCH, type=EventType.CLUE_FOUND,
                      payload={"clue_id": "C01", "location_id": "room_302", "search_cost": 1},
                      visible_to=["*"])
    failures = check_invariants(script, [event, event.model_copy(update={"seq": 2})])
    assert any("duplicate clue" in failure for failure in failures)


def test_invariant_gate_catches_unauthorized_npc_citation(script):
    speech = GameEvent(seq=1, game_id="g", actor_seat_id="system", turn=1,
                       phase=Phase.ACT_OPEN, type=EventType.NPC_SPEECH,
                       payload={"role_id": "chen_yanqiu", "text": "我知道酒壶", "evidence_ids": ["C09"]},
                       visible_to=["*"])
    assert any("unauthorized NPC citation" in failure for failure in check_invariants(script, [speech]))


def test_kappa_requires_paired_labels():
    assert cohen_kappa([0, 1, 0, 1], [0, 1, 0, 1]) == 1
    with pytest.raises(ValueError):
        cohen_kappa([0], [])


def test_model_player_uses_visible_clues_for_vote(script, tmp_path, monkeypatch):
    monkeypatch.setattr("jubensha.eval.simulator.configured", lambda: True)
    monkeypatch.setattr("jubensha.eval.simulator._question", lambda *args: "你知道什么？")
    monkeypatch.setattr("jubensha.agents.npc.configured", lambda: False)
    monkeypatch.setattr("jubensha.engine.guard.configured", lambda: False)
    def plan(store, game_id, node, persona, instruction, public):
        assert "truth_events" not in str(public)
        assert "is_culprit" not in str(public)
        if node == "search_plan":
            return ({"location_id": "room_302", "clue_id": "C02"}
                    if not public["found"] else {"location_id": "room_201", "clue_id": "C04"})
        assert "C04" in public["clues"]
        assert "201 客房" in public["clues"]["C04"]
        return {"role_id": "chen_yanqiu", "motive": "怀表", "evidence_ids": ["C02"]}
    monkeypatch.setattr("jubensha.eval.simulator._model_json", plan)
    store = EventStore(tmp_path / "game.db")
    result = simulate_game(script, store, "speedrun",
                           model_driven=True, variant=1)
    assert result.completed and result.win
    assert any(event.phase == Phase.CONFRONT and event.type == EventType.PLAYER_INPUT
               for event in store.events(result.game_id))
