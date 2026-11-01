import pytest

from jubensha.agents.referee import judge_submission
from jubensha.engine.loop import build_turn_graph, run_turn
from jubensha.engine.replay import replay_at
from jubensha.engine.memory import summaries_for_context
from jubensha.engine.perception import build_perception
from jubensha.schema.events import EventType, GameEvent
from jubensha.schema.genre import GenreProfile
from jubensha.schema.ir import WinCondition
from jubensha.engine.fsm import Phase
from jubensha.storage.events import EventStore


def test_two_seats_share_public_but_not_private(script, tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    store = EventStore(tmp_path / "game.db")
    store.create_game("g", script.script_id, script.acts[0].act_id, seat_id="human")
    store.add_seat("g", "bot", role_id="zhou_shen")
    graph = build_turn_graph(script, store)
    def play(action, seat="human", **kwargs):
        return run_turn(graph, store, script,
                        {"game_id": "g", "actor_seat_id": seat, "action": action, **kwargs})
    play("begin")
    play("read_done")
    play("enter_private", seat="bot", role_id="a_dai")
    play("private_talk", seat="bot", role_id="a_dai", text="只有 bot 问过的秘密")
    play("leave_private", seat="bot")
    play("enter_search", seat="bot")
    play("search", seat="bot", location_id="room_201", clue_id="C04")
    play("leave_search", seat="bot")
    human_state = store.load_for_seat("g", "human", script.acts[0].search_points_budget)
    bot_state = store.load_for_seat("g", "bot", script.acts[0].search_points_budget)
    assert "C04" not in human_state.seats["human"].private_clue_ids
    assert "C04" in bot_state.seats["bot"].private_clue_ids
    assert len(human_state.seats) == len(bot_state.seats) == 1
    assert all("只有 bot 问过的秘密" not in str(event.payload)
               for event in store.events_for_seat("g", "human"))
    assert any("只有 bot 问过的秘密" in str(event.payload)
               for event in store.events_for_seat("g", "bot"))
    role_only = store.append(GameEvent(seq=0, game_id="g", actor_seat_id="system", turn=9,
                                       phase=Phase.ACT_OPEN, type=EventType.NPC_SPEECH,
                                       payload={"text": "周慎角色私有信息", "role_id": "zhou_shen"},
                                       visible_to=["zhou_shen"]))
    assert role_only in store.events_for_seat("g", "bot")
    assert role_only not in store.events_for_seat("g", "human")
    play("enter_confront", seat="bot")
    play("vote", seat="bot", role_id="lin_suyun", motive="私密推理", evidence_ids=["C04"])
    assert store.load_for_seat("g", "human", script.acts[0].search_points_budget).vote_role_id is None
    assert store.load_for_seat("g", "bot", script.acts[0].search_points_budget).vote_motive == "私密推理"
    with pytest.raises(PermissionError):
        store.events_for_seat("g", "intruder")


def test_custom_win_condition_hook_runs_game(script, tmp_path):
    script.win_condition = WinCondition(type="custom", required=[], partial_credit=False)
    profile = GenreProfile(genre="custom", win_condition=script.win_condition,
                           dm_tone="neutral", rubric=[], parser_expectations=[])
    store = EventStore(tmp_path / "game.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    graph = build_turn_graph(script, store)
    def play(action, **kwargs):
        return run_turn(graph, store, script, {"game_id": "g", "action": action, **kwargs})
    for action in ("begin", "read_done", "enter_confront"):
        play(action)
    play("vote", role_id=next(iter(script.characters)), motive="", evidence_ids=[])
    play("recap")
    assert judge_submission(script, store.load("g", script.acts[0].search_points_budget), profile).passed


def test_unknown_event_roundtrips_and_replay_ignores_it(script, tmp_path):
    store = EventStore(tmp_path / "game.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    saved = store.append(GameEvent(seq=0, game_id="g", actor_seat_id="system", turn=1,
                                   phase=Phase.ENTRY, type="voice_segment",
                                   payload={"text": "unsupported extension"}, visible_to=["*"]))
    assert saved.type.value == "voice_segment"
    reloaded = EventStore(tmp_path / "game.db").events("g")
    assert reloaded[0].type.value == "voice_segment"
    state, visible, _ = replay_at(script, store, "g", saved.seq, "seat_1")
    assert state.phase == Phase.ENTRY
    assert len(visible) == 1


def test_accusation_rubric_uses_acquired_evidence(script, state):
    state.vote_role_id = next(key for key, role in script.characters.items() if role.is_culprit)
    state.vote_motive = "欠条"
    state.vote_evidence_ids = ["C04"]
    assert not judge_submission(script, state).outcomes["key_evidence"]
    state.seats["seat_1"].private_clue_ids.append("C04")
    assert judge_submission(script, state).passed


def test_memory_store_hook_accepts_alternate_backend(script, state):
    class InMemorySummaries:
        def __init__(self):
            self.items = {}
        def get(self, game_id, perspective, end_seq):
            return self.items.get((game_id, perspective, end_seq))
        def put(self, summary):
            self.items[(summary.game_id, summary.perspective, summary.end_seq)] = summary
    backend = InMemorySummaries()
    events = [GameEvent(seq=seq, game_id="g", actor_seat_id="system", turn=seq,
                        phase=Phase.ACT_OPEN, type=EventType.PLAYER_INPUT,
                        payload={"text": "讨论现场" * 100}, visible_to=["*"])
              for seq in range(1, 15)]
    perception = build_perception(script, state, "zhou_shen")
    public, role = summaries_for_context(backend, "g", "zhou_shen", events,
                                         perception, "现场？")
    assert public is not None and role is not None
    assert backend.get("g", "zhou_shen", role.end_seq) == role
