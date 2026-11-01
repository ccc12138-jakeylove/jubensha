from jubensha.engine.fsm import Phase
from jubensha.engine.loop import build_turn_graph
from jubensha.storage.events import EventStore


def test_full_game(script, tmp_path):
    store = EventStore(tmp_path / "game.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    graph = build_turn_graph(script, store)

    def play(action, **kwargs):
        return graph.invoke({"game_id": "g", "action": action, **kwargs})

    play("begin")
    play("read_done")
    roles = list(script.characters)
    play("talk", role_id=roles[0], text="你昨晚在哪里？")
    play("talk", role_id=roles[1], text="你看见了什么？")
    play("enter_search")
    result = play("search", location_id=script.clues[next(iter(script.clues))].location_id)
    assert result["clue_id"]
    play("leave_search")
    play("enter_confront")
    play("vote", role_id=roles[0], motive="欠条", evidence_ids=[result["clue_id"]])
    play("recap")
    state = EventStore(tmp_path / "game.db").load("g", script.acts[0].search_points_budget)
    assert state.phase == Phase.RECAP
    assert state.turn == 10
    assert result["clue_id"] in state.public_clue_ids + state.seats["seat_1"].private_clue_ids
    assert [event.seq for event in store.events("g")] == list(range(1, len(store.events("g")) + 1))
