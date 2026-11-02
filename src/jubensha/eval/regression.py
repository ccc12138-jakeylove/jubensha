from jubensha.eval.metrics import EvalMetrics


def regression_reasons(current: EvalMetrics, baseline: EvalMetrics) -> list[str]:
    reasons = []
    if current.normal_win_rate < baseline.normal_win_rate - 0.05:
        reasons.append("normal win rate fell by more than 5 percentage points")
    if current.leak_rate is not None and baseline.leak_rate is not None:
        if current.leak_rate > baseline.leak_rate + 0.01:
            reasons.append("leak rate rose by more than 1 percentage point")
    if current.cost_usd is not None and baseline.cost_usd is not None and baseline.cost_usd > 0:
        if current.cost_usd > baseline.cost_usd * 1.20:
            reasons.append("cost rose by more than 20 percent")
    return reasons
