from jubensha.eval.metrics import EvalMetrics
from jubensha.eval.regression import regression_reasons


def metrics(win: float, leak: float, cost: float) -> EvalMetrics:
    return EvalMetrics(games=20, completed=20, win_rate=win,
                       normal_win_rate=win, stuck_rate=0, leak_rate=leak,
                       mean_turns=10, invariant_failures=0, model_evaluated=True,
                       cost_usd=cost)


def test_regression_gate_catches_three_material_degradations():
    baseline = metrics(0.85, 0.01, 1.0)
    assert regression_reasons(metrics(0.79, 0.03, 1.3), baseline) == [
        "normal win rate fell by more than 5 percentage points",
        "leak rate rose by more than 1 percentage point",
        "cost rose by more than 20 percent",
    ]
    assert regression_reasons(metrics(0.84, 0.01, 1.1), baseline) == []
