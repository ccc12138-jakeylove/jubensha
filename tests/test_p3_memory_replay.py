from jubensha.engine.context import build_context, context_size
from jubensha.engine.memory import summaries_for_context
from jubensha.engine.perception import build_perception
from jubensha.engine.replay import reference_evidence, replay_at
from jubensha.engine.fsm import Phase
from jubensha.schema.events import EventType, GameEvent
from jubensha.storage.events import EventStore
from jubensha.storage.memory import SummaryStore


def add_event(store, game_id, turn, kind, payload, visible):
    return store.append(GameEvent(seq=0, game_id=game_id, actor_seat_id="system",
                                  turn=turn, phase=Phase.ACT_OPEN, type=kind,
                                  payload=payload, visible_to=visible))


def test_summaries_are_perspective_isolated_and_persisted(script, state, tmp_path):
    store = EventStore(tmp_path / "game.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    add_event(store, "g", 1, EventType.PLAYER_INPUT, {"text": "只有阿黛听见的私聊"}, ["seat_1", "a_dai"])
    add_event(store, "g", 1, EventType.NPC_SPEECH,
              {"text": "我不记得了", "role_id": "a_dai"}, ["seat_1", "a_dai"])
    for turn in range(2, 15):
        add_event(store, "g", turn, EventType.PLAYER_INPUT,
                  {"text": f"公开讨论第{turn}轮" + "那晚的时间和地点。" * 35}, ["*"])
    events = store.events("g")
    summary_store = SummaryStore(store)
    public, a_dai = summaries_for_context(summary_store, "g", "a_dai", events,
                                           build_perception(script, state, "a_dai"), "那晚呢？")
    _, zhou = summaries_for_context(summary_store, "g", "zhou_shen", events,
                                     build_perception(script, state, "zhou_shen"), "那晚呢？")
    assert public is not None and a_dai is not None and zhou is not None
    assert "只有阿黛" not in public.text
    assert "只有阿黛" in a_dai.text
    assert "我说" in a_dai.text
    assert "只有阿黛" not in zhou.text
    assert SummaryStore(EventStore(tmp_path / "game.db")).get("g", "a_dai", a_dai.end_seq) == a_dai


def test_layered_context_is_smaller_than_full(script, state, tmp_path):
    store = EventStore(tmp_path / "game.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    for turn in range(1, 35):
        add_event(store, "g", turn, EventType.PLAYER_INPUT,
                  {"text": f"第{turn}轮询问：" + "那晚的时间和地点。" * 20}, ["*"])
    events = store.events("g")
    perception = build_perception(script, state, "chen_yanqiu")
    public, role = summaries_for_context(SummaryStore(store), "g", "chen_yanqiu",
                                         events, perception, "你在哪里？")
    full = build_context(perception, "你在哪里？", events, mode="full")
    layered = build_context(perception, "你在哪里？", events,
                            public_summary=public, role_summary=role, mode="layered")
    assert context_size(full) > context_size(layered)
    assert context_size(layered) <= 3000
    assert all(f"L{i}" in layered[i - 1]["content"] for i in range(1, 7))


def test_replay_rebuilds_historic_state_and_filters_private_clue(script, tmp_path):
    store = EventStore(tmp_path / "game.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    add_event(store, "g", 1, EventType.DM_NARRATION, {"text": "开场"}, ["*"])
    clue = add_event(store, "g", 2, EventType.CLUE_FOUND,
                     {"clue_id": "C07", "location_id": "room_105", "search_cost": 1}, ["seat_1"])
    before, _, _ = replay_at(script, store, "g", clue.seq - 1, "seat_1")
    after, visible, _ = replay_at(script, store, "g", clue.seq, "seat_1")
    _, other_visible, other_perception = replay_at(script, store, "g", clue.seq, "zhou_shen")
    assert "C07" not in before.seats["seat_1"].private_clue_ids
    assert "C07" in after.seats["seat_1"].private_clue_ids
    assert clue.seq in [event.seq for event in visible]
    assert clue.seq not in [event.seq for event in other_visible]
    assert "C07" not in other_perception.model_dump_json()
    assert set(reference_evidence(script)).issubset(script.clues)
