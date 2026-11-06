from jubensha.agents.npc import respond
from jubensha.engine.perception import build_perception
from jubensha.storage.events import EventStore
from jubensha.engine.loop import build_turn_graph, run_turn
from jubensha.schema.events import EventType


def test_model_selects_only_authorized_fact(script, state, tmp_path, monkeypatch):
    monkeypatch.setattr("jubensha.agents.npc.configured", lambda: True)
    monkeypatch.setenv("NPC_GENERATION_MODE", "grounded")
    def select(store, game_id, node, version, messages, **kwargs):
        assert node == "npc_select" and kwargs["json_mode"] is True
        assert script.secrets["S02"].content not in str(messages)
        return '{"source_id":"C02"}'
    monkeypatch.setattr("jubensha.agents.npc.generate", select)
    perception = build_perception(script, state, "lin_suyun")
    response = respond(perception, "怀表呢？", [], EventStore(tmp_path / "game.db"), "g")
    assert response.text == "我只看到：" + script.clues["C02"].surface_text
    assert response.evidence_ids == ["C02"]
    assert not response.is_lie


def test_unknown_selection_cannot_emit_model_text(script, state, tmp_path, monkeypatch):
    monkeypatch.setattr("jubensha.agents.npc.configured", lambda: True)
    monkeypatch.setenv("NPC_GENERATION_MODE", "grounded")
    secret = script.secrets["S02"].content
    monkeypatch.setattr("jubensha.agents.npc.generate", lambda *args, **kwargs:
                        '{"source_id":"S02","reply":"' + secret + '"}')
    perception = build_perception(script, state, "lin_suyun")
    response = respond(perception, "你昨晚在哪？", [], EventStore(tmp_path / "game.db"), "g")
    assert secret not in response.text
    assert response.evidence_ids == []


def test_irrelevant_authorized_clue_is_not_forced_into_answer(script, state, tmp_path, monkeypatch):
    monkeypatch.setattr("jubensha.agents.npc.configured", lambda: True)
    monkeypatch.setenv("NPC_GENERATION_MODE", "grounded")
    monkeypatch.setattr("jubensha.agents.npc.generate", lambda *args, **kwargs:
                        '{"source_id":"C01"}')
    perception = build_perception(script, state, "lin_suyun")
    response = respond(perception, "案发时你在哪里？", [], EventStore(tmp_path / "game.db"), "g")
    assert "酒渍" not in response.text
    assert response.evidence_ids == []


def test_grounded_source_is_written_to_speech_and_claim(script, tmp_path, monkeypatch):
    monkeypatch.setattr("jubensha.agents.npc.configured", lambda: True)
    monkeypatch.setattr("jubensha.engine.guard.configured", lambda: False)
    monkeypatch.setenv("NPC_GENERATION_MODE", "grounded")
    monkeypatch.setattr("jubensha.agents.npc.generate", lambda *args, **kwargs:
                        '{"source_id":"C02"}')
    store = EventStore(tmp_path / "game.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    graph = build_turn_graph(script, store)
    for action in ("begin", "read_done"):
        run_turn(graph, store, script, {"game_id": "g", "action": action})
    run_turn(graph, store, script, {"game_id": "g", "action": "talk",
                                        "role_id": "lin_suyun", "text": "怀表呢？"})
    events = store.events("g")
    for kind in (EventType.NPC_SPEECH, EventType.CLAIM):
        own = next(event for event in events if event.type == kind
                   and event.payload.get("role_id") == "lin_suyun")
        assert own.payload["evidence_ids"] == ["C02"]


def test_public_accusation_does_not_repeat_one_fallback_for_every_role(script, tmp_path, monkeypatch):
    monkeypatch.setattr("jubensha.agents.npc.configured", lambda: True)
    monkeypatch.setattr("jubensha.engine.guard.configured", lambda: False)
    monkeypatch.setattr("jubensha.agents.npc.generate", lambda *args, **kwargs:
                        '{"source_id":"none"}')
    store = EventStore(tmp_path / "public_question.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    graph = build_turn_graph(script, store)
    for action in ("begin", "read_done"):
        run_turn(graph, store, script, {"game_id": "g", "action": action})
    run_turn(graph, store, script, {"game_id": "g", "action": "talk",
                                        "text": "我觉得凶手在你们之中"})
    speeches = [event for event in store.events("g") if event.type == EventType.NPC_SPEECH]
    assert len(speeches) >= 2
    assert len({event.payload["text"] for event in speeches}) == len(speeches)


def test_profile_selection_on_accusation_uses_role_observation(script, state, tmp_path, monkeypatch):
    monkeypatch.setattr("jubensha.agents.npc.configured", lambda: True)
    monkeypatch.setattr("jubensha.agents.npc.generate", lambda *args, **kwargs:
                        '{"source_id":"profile"}')
    store = EventStore(tmp_path / "accusation.db")
    response = respond(build_perception(script, state, "lin_suyun"),
                       "我觉得凶手在你们之中", [], store, "g")
    assert "302 有争吵声" in response.text
    assert response.evidence_ids == ["E01"]
