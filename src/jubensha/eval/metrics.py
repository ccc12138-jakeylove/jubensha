from pydantic import BaseModel, ConfigDict


class EvalMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    games: int
    completed: int
    win_rate: float
    normal_win_rate: float = 0
    culprit_rate: float = 0
    stuck_rate: float
    leak_rate: float | None
    raw_risk_rate: float | None = None
    mean_turns: float
    invariant_failures: int
    model_evaluated: bool
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    p95_latency_ms: float | None = None
    judge_mean: float | None = None


def cohen_kappa(human: list[int], model: list[int]) -> float:
    if len(human) != len(model) or not human:
        raise ValueError("labels must be paired and nonempty")
    labels = set(human) | set(model)
    observed = sum(a == b for a, b in zip(human, model)) / len(human)
    expected = sum((human.count(label) / len(human)) * (model.count(label) / len(model))
                   for label in labels)
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[int(0.95 * (len(ordered) - 1))]
