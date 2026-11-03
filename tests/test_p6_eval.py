import pytest

from jubensha.eval.invariants import check_invariants
from jubensha.eval.metrics import cohen_kappa
from jubensha.eval.simulator import PERSONAS, _choose_search, _choose_vote, simulate_game
from jubensha.schema.events import EventType, GameEvent
from jubensha.schema.ir import Act
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


def test_offline_simulator_searches_beyond_one_target(script, tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    store = EventStore(tmp_path / "multi_search.db")
    result = simulate_game(script, store, "speedrun")
    found = [event for event in store.events(result.game_id) if event.type == EventType.CLUE_FOUND]
    assert result.completed and not result.errors
    assert len(found) >= 2


def test_simulator_skips_vote_for_non_vote_act(script, tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    script = script.model_copy(deep=True)
    script.acts[0].requires_vote = False
    script.acts.append(Act(act_id="A2", order=2, title="终幕", public_narrative="真相揭晓。",
                           allowed_phases=[Phase.READ, Phase.ACT_OPEN, Phase.CONFRONT, Phase.VOTE],
                           search_points_budget=2))
    store = EventStore(tmp_path / "non_vote_eval.db")
    result = simulate_game(script, store, "speedrun")
    assert result.completed and not result.errors
    votes = [event for event in store.events(result.game_id) if event.type == EventType.VOTE]
    assert len(votes) == 1
    assert store.load(result.game_id, 2).phase == Phase.END


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
        return {"role_id": "lin_suyun", "motive": "欠条", "evidence_ids": ["C04"]}
    monkeypatch.setattr("jubensha.eval.simulator._model_json", plan)
    store = EventStore(tmp_path / "game.db")
    result = simulate_game(script, store, "speedrun",
                           model_driven=True, variant=1)
    assert result.completed and result.win
    assert any(event.phase == Phase.CONFRONT and event.type == EventType.PLAYER_INPUT
               for event in store.events(result.game_id))


def test_search_planner_sees_only_presearch_label(script, tmp_path, monkeypatch):
    script = script.model_copy(deep=True)
    script.clues["C02"].search_label = "待搜查目标 1"
    script.clues["C02"].display_name = "未公开的线索内容"
    store = EventStore(tmp_path / "planner.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    monkeypatch.setattr("jubensha.eval.simulator.configured", lambda: True)

    def plan(store, game_id, node, persona, instruction, public):
        option = next(item for item in public["options"] if item["clue_id"] == "C02")
        assert option["target"] == "待搜查目标 1"
        assert "未公开的线索内容" not in str(public)
        return {"location_id": option["location_id"], "clue_id": "C02"}

    monkeypatch.setattr("jubensha.eval.simulator._model_json", plan)
    assert _choose_search(script, store, "g", "speedrun", True)[1].clue_id == "C02"


def test_bundle_search_accepts_any_clue_at_chosen_location(script, tmp_path, monkeypatch):
    script = script.model_copy(deep=True)
    script.search_mode = "location_bundle"
    store = EventStore(tmp_path / "bundle_planner.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    monkeypatch.setattr("jubensha.eval.simulator.configured", lambda: True)
    # 地点包只按地点结算；模型回填同地点另一条线索时不能退回兜底地点。
    monkeypatch.setattr("jubensha.eval.simulator._model_json",
                        lambda *args: {"location_id": "room_302", "clue_id": "C01"})
    location_id, _ = _choose_search(script, store, "g", "speedrun", True)
    assert location_id == "room_302"


def test_vote_planner_preserves_valid_model_choice_without_word_overlap(script, tmp_path, monkeypatch):
    store = EventStore(tmp_path / "vote_planner.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    store.append(GameEvent(seq=0, game_id="g", actor_seat_id="seat_1", turn=1,
                           phase=Phase.SEARCH, type=EventType.CLUE_FOUND,
                           payload={"clue_id": "C04", "location_id": "room_201", "search_cost": 1},
                           visible_to=["seat_1"]))
    monkeypatch.setattr("jubensha.eval.simulator.configured", lambda: True)
    monkeypatch.setattr("jubensha.eval.simulator._model_json",
                        lambda *args: {"role_id": "lin_suyun", "motive": "为了摆脱旧事",
                                       "evidence_ids": ["C04"]})
    assert _choose_vote(script, store, "g", "speedrun", True, "a_dai") == (
        "lin_suyun", "为了摆脱旧事", ["C04"])


def test_vote_prompt_stays_generic_for_any_script(script, tmp_path, monkeypatch):
    store = EventStore(tmp_path / "vote_prompt.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    store.append(GameEvent(seq=0, game_id="g", actor_seat_id="seat_1", turn=1,
                           phase=Phase.SEARCH, type=EventType.CLUE_FOUND,
                           payload={"clue_id": "C04", "location_id": "room_201", "search_cost": 1},
                           visible_to=["seat_1"]))
    captured = {}
    monkeypatch.setattr("jubensha.eval.simulator.configured", lambda: True)
    def plan(store, game_id, node, persona, instruction, public):
        captured.update(instruction=instruction, public=public)
        return {"role_id": "lin_suyun", "motive": "为了拿回欠条", "evidence_ids": ["C04"]}
    monkeypatch.setattr("jubensha.eval.simulator._model_json", plan)
    assert _choose_vote(script, store, "g", "speedrun", True, "a_dai")[0] == "lin_suyun"
    assert "欠条" not in captured["instruction"]
    assert "C04" in captured["public"]["clues"]


def test_invalid_model_vote_records_fallback_instead_of_name_guessing(script, tmp_path, monkeypatch):
    store = EventStore(tmp_path / "vote_invalid.db")
    store.create_game("g", script.script_id, script.acts[0].act_id)
    store.append(GameEvent(seq=0, game_id="g", actor_seat_id="seat_1", turn=1,
                           phase=Phase.SEARCH, type=EventType.CLUE_FOUND,
                           payload={"clue_id": "C04", "location_id": "room_201", "search_cost": 1},
                           visible_to=["seat_1"]))
    monkeypatch.setattr("jubensha.eval.simulator.configured", lambda: True)
    monkeypatch.setattr("jubensha.eval.simulator._model_json",
                        lambda *args: (_ for _ in ()).throw(ValueError("bad json")))
    diagnostics = []
    role_id, motive, evidence = _choose_vote(
        script, store, "g", "speedrun", True, "a_dai", diagnostics)
    # C04 文本里出现“林素云”，但无效输出不能再按名字频率猜人。
    assert role_id == "a_dai"
    assert "模型未返回" in motive
    assert evidence == ["C04"]
    assert diagnostics == ["invalid_model_vote"]


def test_simulated_game_surfaces_invalid_model_vote(script, tmp_path, monkeypatch):
    monkeypatch.setattr("jubensha.eval.simulator.configured", lambda: True)
    monkeypatch.setattr("jubensha.agents.npc.configured", lambda: False)
    monkeypatch.setattr("jubensha.engine.guard.configured", lambda: False)
    monkeypatch.setattr("jubensha.eval.simulator._question", lambda *args: "你知道什么？")
    monkeypatch.setattr("jubensha.eval.simulator._model_json",
                        lambda *args: (_ for _ in ()).throw(ValueError("bad json")))
    store = EventStore(tmp_path / "invalid_vote.db")
    result = simulate_game(script, store, "speedrun", model_driven=True, variant=1)
    assert result.completed
    assert result.invalid_model_votes == 1
    assert "invalid_model_vote" in result.attributions
