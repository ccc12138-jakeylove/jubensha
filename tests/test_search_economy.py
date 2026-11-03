import pytest

from jubensha.engine.loop import build_turn_graph, run_turn
from jubensha.engine.search import available_clues
from jubensha.engine.fsm import Phase
from jubensha.eval.invariants import check_invariants
from jubensha.schema.ir import Act
from jubensha.storage.events import EventStore


def test_cost_prerequisite_and_replay(script, tmp_path):
    store = EventStore(tmp_path / "game.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    graph = build_turn_graph(script, store)
    def play(action, **kwargs):
        return run_turn(graph, store, script, {"game_id": "g", "action": action, **kwargs})
    play("begin")
    play("read_done")
    play("enter_search")
    with pytest.raises(ValueError):
        play("search", location_id="room_302", clue_id="C06")
    play("search", location_id="room_302", clue_id="C05")
    play("search", location_id="room_302", clue_id="C06")
    restored = EventStore(tmp_path / "game.db").load("g", script.acts[0].search_points_budget)
    assert restored.seats["seat_1"].search_points == 0
    assert restored.search_counts["room_302"] == 2
    assert {"C05", "C06"}.issubset(restored.public_clue_ids)
    assert available_clues(script, restored, "room_302") == []
    with pytest.raises(ValueError):
        play("search", location_id="room_302", clue_id="C01")


def test_location_capacity(script, tmp_path):
    store = EventStore(tmp_path / "game.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    graph = build_turn_graph(script, store)
    for action in ("begin", "read_done", "enter_search"):
        run_turn(graph, store, script, {"game_id": "g", "action": action})
    run_turn(graph, store, script, {"game_id": "g", "action": "search", "location_id": "room_201", "clue_id": "C04"})
    state = store.load("g", script.acts[0].search_points_budget)
    assert state.search_counts["room_201"] == script.locations["room_201"].capacity_per_act
    assert available_clues(script, state, "room_201") == []


def test_private_chat_budget_and_visibility(script, tmp_path):
    store = EventStore(tmp_path / "game.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    graph = build_turn_graph(script, store)
    def play(action, **kwargs):
        return run_turn(graph, store, script, {"game_id": "g", "action": action, **kwargs})
    play("begin")
    play("read_done")
    play("enter_private", role_id="a_dai")
    play("private_talk", role_id="a_dai", text="你知道什么？")
    with pytest.raises(ValueError):
        play("private_talk", role_id="zhou_shen", text="你好")
    play("leave_private")
    play("enter_private", role_id="zhou_shen")
    play("leave_private")
    restored = EventStore(tmp_path / "game.db").load("g", script.acts[0].search_points_budget)
    assert restored.private_chats_used == 2
    with pytest.raises(ValueError):
        play("enter_private", role_id="a_dai")
    private_events = [e for e in store.events("g") if e.payload.get("private")]
    assert private_events and private_events[0].visible_to == ["seat_1", "a_dai"]


def test_next_act_resets_budgets_and_preserves_clues(script, tmp_path):
    script.acts.append(Act(act_id="A2", order=2, title="第二幕", public_narrative="第二幕开始。",
                           allowed_phases=list(Phase), search_points_budget=2, private_chat_budget=1))
    store = EventStore(tmp_path / "game.db")
    store.create_game("g", script.script_id, "A1")
    graph = build_turn_graph(script, store)
    def play(action, **kwargs):
        return run_turn(graph, store, script, {"game_id": "g", "action": action, **kwargs})
    play("begin")
    play("read_done")
    play("enter_search")
    play("search", location_id="room_201", clue_id="C04")
    play("leave_search")
    play("enter_private", role_id="a_dai")
    play("leave_private")
    play("enter_confront")
    play("vote", role_id="a_dai", motive="猜测", evidence_ids=["C04"])
    play("next_act")
    state = EventStore(tmp_path / "game.db").load("g", script.acts[0].search_points_budget)
    assert state.phase == Phase.READ
    assert state.act_id == "A2"
    assert state.seats["seat_1"].search_points == 2
    assert state.private_chats_used == 0
    assert state.search_counts == {}
    assert "C04" in state.seats["seat_1"].private_clue_ids


def test_location_bundle_costs_one_point_and_respects_prerequisites(script, tmp_path):
    script = script.model_copy(deep=True)
    script.search_mode = "location_bundle"
    script.acts[0].search_points_budget = 2
    script.locations["room_302"].capacity_per_act = 5
    store = EventStore(tmp_path / "bundle.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    graph = build_turn_graph(script, store)
    def play(action, **kwargs):
        return run_turn(graph, store, script, {"game_id": "g", "action": action, **kwargs})
    for action in ("begin", "read_done", "enter_search"):
        play(action)
    play("search_bundle", location_id="room_302")
    first = store.load("g", 2)
    assert first.seats["seat_1"].search_points == 1
    assert {"C01", "C02", "C05"}.issubset(first.public_clue_ids)
    assert "C06" not in first.public_clue_ids
    play("search_bundle", location_id="room_302")
    final = store.load("g", 2)
    assert final.seats["seat_1"].search_points == 0
    assert {"C06", "C09"}.issubset(final.public_clue_ids)
    assert not check_invariants(script, store.events("g"))
    with pytest.raises(ValueError):
        play("search_bundle", location_id="room_302")
