from concurrent.futures import ThreadPoolExecutor

from jubensha.engine.loop import build_turn_graph, run_turn
from jubensha.storage.events import EventStore


def test_ten_parallel_games_keep_contiguous_events_and_private_state(script, tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    store = EventStore(tmp_path / "parallel.db")

    def play(index: int):
        game_id = f"game_{index}"
        store.create_game(game_id, script.script_id, script.acts[0].act_id)
        graph = build_turn_graph(script, store)
        for action, extra in (
            ("begin", {}), ("read_done", {}), ("enter_search", {}),
            ("search", {"location_id": "room_201", "clue_id": "C04"}),
            ("leave_search", {}),
        ):
            run_turn(graph, store, script, {"game_id": game_id, "action": action, **extra})
        state = store.load_for_seat(game_id, "seat_1", script.acts[0].search_points_budget)
        events = store.events(game_id)
        return state, events

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(play, range(10)))
    assert len(results) == 10
    for index, (state, events) in enumerate(results):
        assert state.game_id == f"game_{index}"
        assert state.seats["seat_1"].private_clue_ids == ["C04"]
        assert [event.seq for event in events] == list(range(1, len(events) + 1))
        assert all(event.game_id == state.game_id for event in events)
