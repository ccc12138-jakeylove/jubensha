import pytest

from jubensha.engine.fsm import Phase, TRANSITIONS, transition
from jubensha.engine.loop import build_turn_graph, run_turn
from jubensha.storage.events import EventStore


def test_all_transitions():
    for source in Phase:
        for target in Phase:
            if target in TRANSITIONS[source]:
                assert transition(source, target, last_act=target != Phase.READ or source != Phase.VOTE) == target
            else:
                with pytest.raises(ValueError):
                    transition(source, target)
    with pytest.raises(ValueError):
        transition(Phase.SEARCH, Phase.VOTE)
    with pytest.raises(ValueError):
        transition(Phase.VOTE, Phase.RECAP, last_act=False)


def test_act_configuration_blocks_disallowed_search(script, tmp_path):
    restricted = script.model_copy(deep=True)
    restricted.acts[0].allowed_phases.remove(Phase.SEARCH)
    store = EventStore(tmp_path / "restricted.db")
    store.create_game("g", restricted.script_id, restricted.acts[0].act_id)
    graph = build_turn_graph(restricted, store)
    for action in ("begin", "read_done"):
        run_turn(graph, store, restricted, {"game_id": "g", "action": action})
    with pytest.raises(ValueError, match="search"):
        run_turn(graph, store, restricted, {"game_id": "g", "action": "enter_search"})
