from jubensha.agents.judge import judge_response
from jubensha.eval.harness import render_report, run_eval
from jubensha.eval.simulator import SimResult
from jubensha.storage.events import EventStore
from jubensha.storage.evals import EvalStore


def test_offline_eval_report(script, tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    store = EventStore(tmp_path / "game.db")
    report = run_eval(script, store, games_per_persona=1)
    assert report.metrics.games == 4
    assert report.metrics.completed == 4
    assert report.metrics.leak_rate is None
    assert report.gate_passed
    assert EvalStore(store).list_runs(script.script_id)[0]["run_id"] == report.run_id
    assert "未测" in render_report(report, script.title)


def test_judge_receives_only_authorized_context(tmp_path, monkeypatch):
    store = EventStore(tmp_path / "game.db")
    monkeypatch.setattr("jubensha.agents.judge.configured", lambda: True)
    def stub(store, game_id, node, version, messages, max_tokens=300):
        assert node == "eval_judge"
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
