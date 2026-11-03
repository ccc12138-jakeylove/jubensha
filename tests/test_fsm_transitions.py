import pytest

from jubensha.compiler.lint import lint_script
from jubensha.engine.fsm import Phase, TRANSITIONS, transition
from jubensha.engine.loop import build_turn_graph, run_turn
from jubensha.schema.ir import Act
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


def test_non_vote_act_advances_from_confront(script, tmp_path):
    script = script.model_copy(deep=True)
    script.acts[0].requires_vote = False
    script.acts.append(Act(act_id="A2", order=2, title="终幕", public_narrative="真相揭晓。",
                           allowed_phases=[Phase.READ, Phase.ACT_OPEN, Phase.CONFRONT, Phase.VOTE],
                           search_points_budget=2))
    store = EventStore(tmp_path / "non_vote_act.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    graph = build_turn_graph(script, store)

    def play(action, **kwargs):
        return run_turn(graph, store, script, {"game_id": "g", "action": action, **kwargs})

    play("begin")
    play("read_done")
    play("enter_confront")
    with pytest.raises(ValueError, match="不进行投票"):
        play("vote", role_id="a_dai", motive="", evidence_ids=[])
    play("next_act")
    state = store.load("g", script.acts[0].search_points_budget)
    assert state.act_id == "A2" and state.phase == Phase.READ
    play("read_done")
    play("enter_confront")
    play("vote", role_id="a_dai", motive="", evidence_ids=[])
    play("recap")
    assert store.load("g", script.acts[1].search_points_budget).phase == Phase.RECAP


def test_lint_requires_vote_in_final_act(script):
    script = script.model_copy(deep=True)
    script.acts[0].requires_vote = False
    report = lint_script(script)
    assert "FINAL_ACT_REQUIRES_VOTE" in {item.code for item in report.blockers}


def test_transition_allows_non_vote_advance_only_when_configured():
    assert transition(Phase.CONFRONT, Phase.READ, last_act=False,
                      requires_vote=False) == Phase.READ
    with pytest.raises(ValueError):
        transition(Phase.CONFRONT, Phase.READ, last_act=False, requires_vote=True)
    with pytest.raises(ValueError):
        transition(Phase.CONFRONT, Phase.READ, last_act=True, requires_vote=False)
