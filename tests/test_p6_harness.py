import json

from jubensha.agents.judge import judge_response
from jubensha.eval.harness import render_report, run_eval
from jubensha.eval.simulator import SimResult
from jubensha.engine.probes import Probe
from jubensha.engine.guard import check_npc_output
from jubensha.engine.perception import build_perception
from jubensha.schema.state import GameState, SeatState
from jubensha.storage.events import EventStore
from jubensha.storage.evals import EvalStore


def test_offline_eval_report(script, tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    store = EventStore(tmp_path / "game.db")
    report = run_eval(script, store, games_per_persona=1)
    assert report.metrics.games == 4
    assert report.metrics.completed == 4
    assert report.metrics.leak_rate is None
    assert report.metrics.normal_win_rate >= 0
    assert report.gate_passed
    assert EvalStore(store).list_runs(script.script_id)[0]["run_id"] == report.run_id
    assert len(json.loads(EvalStore(store).list_runs(script.script_id)[0]["results_json"])) == 4
    assert "未测" in render_report(report, script.title)
    assert report.ir_sha256 and "IR SHA256" in render_report(report, script.title)


def test_judge_receives_only_authorized_context(tmp_path, monkeypatch):
    store = EventStore(tmp_path / "game.db")
    monkeypatch.setattr("jubensha.agents.judge.configured", lambda: True)
    def stub(store, game_id, node, version, messages, max_tokens=300, json_mode=False):
        assert node == "eval_judge"
        assert json_mode
        assert "truth_events" not in str(messages)
        return '{"in_character":4,"consistent":5,"grounded":4,"natural":3,"reason":"符合角色"}'
    monkeypatch.setattr("jubensha.agents.judge.generate", stub)
    result = judge_response(store, "g", "旅馆老板", ["看见门闩"], ["你看到什么"], "我只看见门闩")
    assert result.consistent == 5


def test_eval_gate_rejects_invariant_regression(script, tmp_path, monkeypatch):
    store = EventStore(tmp_path / "game.db")
    def broken_simulator(script, store, persona, **kwargs):
        return SimResult(game_id=f"bad_{persona}", persona=persona, completed=True,
                         win=False, turns=1, clue_ids=[], proactive_count=2,
                         stuck_level2=False, invariant_failures=["duplicate clue"], errors=[])
    monkeypatch.setattr("jubensha.eval.harness.simulate_game", broken_simulator)
    report = run_eval(script, store, games_per_persona=1)
    assert not report.gate_passed
    assert report.metrics.invariant_failures == 4


def test_live_probe_uses_game_guard_path(script, tmp_path, monkeypatch):
    store = EventStore(tmp_path / "game.db")
    monkeypatch.setattr("jubensha.eval.harness.configured", lambda: True)
    monkeypatch.setattr("jubensha.agents.npc.configured", lambda: True)
    monkeypatch.setattr("jubensha.agents.npc.generate", lambda *args, **kwargs: "我没看见。")
    monkeypatch.setattr("jubensha.engine.guard.configured", lambda: False)
    monkeypatch.setattr("jubensha.eval.harness.generate_probes", lambda script: [
        Probe(role_id="a_dai", target="S04", style="direct", prompt="你父亲是谁？",
              forbidden_surfaces=[script.leak_surfaces["S04"].fact])])
    def fake_sim(script, store, persona, **kwargs):
        return SimResult(game_id=f"fake_{persona}", persona=persona, completed=True,
                         win=False, turns=1, clue_ids=[], proactive_count=2,
                         stuck_level2=False, invariant_failures=[], errors=[])
    monkeypatch.setattr("jubensha.eval.harness.simulate_game", fake_sim)
    report = run_eval(script, store, games_per_persona=1, live_model=True)
    assert report.metrics.leak_rate == 0
    assert report.metrics.raw_risk_rate == 0
    assert report.probe_hits == 0
    assert not report.gate_passed  # Four games are only a smoke sample.


def test_live_probe_counts_blocked_candidate_separately(script, tmp_path, monkeypatch):
    store = EventStore(tmp_path / "game.db")
    monkeypatch.setenv("NPC_GENERATION_MODE", "freeform")
    monkeypatch.setattr("jubensha.eval.harness.configured", lambda: True)
    monkeypatch.setattr("jubensha.agents.npc.configured", lambda: True)
    monkeypatch.setattr("jubensha.agents.npc.generate",
                        lambda *args, **kwargs: script.leak_surfaces["S02"].fact)
    monkeypatch.setattr("jubensha.engine.guard.configured", lambda: False)
    monkeypatch.setattr("jubensha.eval.harness.generate_probes", lambda script: [
        Probe(role_id="lin_suyun", target="S02", style="direct", prompt="怀表是谁调的？",
              forbidden_surfaces=[script.leak_surfaces["S02"].fact])])
    def fake_sim(script, store, persona, **kwargs):
        return SimResult(game_id=f"fake_{persona}", persona=persona, completed=True,
                         win=False, turns=1, clue_ids=[], proactive_count=2,
                         stuck_level2=False, invariant_failures=[], errors=[])
    monkeypatch.setattr("jubensha.eval.harness.simulate_game", fake_sim)
    report = run_eval(script, store, games_per_persona=1, live_model=True)
    assert report.metrics.raw_risk_rate == 1
    assert report.metrics.leak_rate == 0


def test_answering_asked_forbidden_topic_is_not_automatic_leak(script):
    state = GameState(game_id="g", script_id=script.script_id, act_id=script.acts[0].act_id,
                      seats={"seat_1": SeatState(seat_id="seat_1")})
    perception = build_perception(script, state, "zhou_shen")
    answer = "那些账目传闻是胡说，我没见到证据。"
    assert check_npc_output(script, perception, answer, "你的账目有什么问题？")
    assert not check_npc_output(script, perception, answer, "案发时你在哪？")
