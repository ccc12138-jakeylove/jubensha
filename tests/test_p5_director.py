from jubensha.agents.director import decide
from jubensha.engine.fsm import Phase
from jubensha.engine.loop import build_turn_graph, run_turn
from jubensha.schema.events import EventType, GameEvent
from jubensha.storage.events import EventStore


def event(seq, turn, kind, payload):
    return GameEvent(seq=seq, game_id="g", actor_seat_id="system", turn=turn,
                     phase=Phase.ACT_OPEN, type=kind, payload=payload, visible_to=["*"])


def test_director_stall_levels():
    history = [event(1, 1, EventType.PHASE_CHANGE, {"to": "act_open"})]
    profiles = {f"role_{index}": "公开人设" for index in range(4)}
    for turn in range(2, 19):
        history.append(event(3 * turn, turn, EventType.PLAYER_INPUT,
                             {"text": "还是没有进展", "role_id": "role_0"}))
        history.append(event(3 * turn + 1, turn, EventType.CLAIM,
                             {"role_id": "role_0", "proposition": "同一句话"}))
        if turn == 10:
            first = decide(Phase.ACT_OPEN, history, profiles)
        if turn == 14:
            second = decide(Phase.ACT_OPEN, history, profiles)
    third = decide(Phase.ACT_OPEN, history, profiles)
    assert (first.action, first.level) == ("proactive", 1)
    assert (second.action, second.level) == ("hint", 2)
    assert (third.action, third.level) == ("hint", 3)


def test_public_fanout_and_proactive_turns(script, tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    store = EventStore(tmp_path / "game.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    graph = build_turn_graph(script, store)
    for action in ("begin", "read_done"):
        run_turn(graph, store, script, {"game_id": "g", "action": action})
    run_turn(graph, store, script, {"game_id": "g", "action": "talk",
                                         "role_id": "", "text": "那晚你们在哪里？"})
    run_turn(graph, store, script, {"game_id": "g", "action": "talk",
                                         "role_id": "lin_suyun", "text": "你怎么看？"})
    speeches = [item for item in store.events("g") if item.type == EventType.NPC_SPEECH]
    assert len(speeches) >= 4
    assert len({item.payload["role_id"] for item in speeches}) >= 3
    assert sum(bool(item.payload.get("proactive")) for item in speeches) >= 2


def test_public_clue_triggers_one_reaction(script, tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    store = EventStore(tmp_path / "game.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    graph = build_turn_graph(script, store)
    def play(action, **kwargs):
        return run_turn(graph, store, script, {"game_id": "g", "action": action, **kwargs})
    for action in ("begin", "read_done", "enter_search"):
        play(action)
    play("search", location_id="room_302", clue_id="C01")
    play("leave_search")
    play("talk", role_id="lin_suyun", text="这是谁的杯子？")
    play("talk", role_id="lin_suyun", text="还有什么？")
    reactions = [event for event in store.events("g") if event.type == EventType.NPC_SPEECH
                 and event.payload.get("trigger_clue_id") == "C01"]
    assert len(reactions) == 1
