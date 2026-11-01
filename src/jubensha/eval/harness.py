from statistics import mean
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from jubensha.agents.npc import respond
from jubensha.agents.judge import judge_response
from jubensha.engine.guard import check_npc_output, semantic_leak_check
from jubensha.engine.perception import build_perception
from jubensha.engine.probes import generate_probes
from jubensha.engine.replay import replay_at
from jubensha.eval.metrics import EvalMetrics, p95
from jubensha.eval.simulator import PERSONAS, SimResult, simulate_game
from jubensha.llm.gateway import configured
from jubensha.schema.ir import Script
from jubensha.schema.events import EventType
from jubensha.schema.state import GameState, SeatState
from jubensha.storage.events import EventStore
from jubensha.storage.evals import EvalStore


class EvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    script_id: str
    metrics: EvalMetrics
    results: list[SimResult]
    probe_count: int
    probe_hits: int | None
    gate_passed: bool
    limitations: list[str]


def run_eval(script: Script, store: EventStore, *, games_per_persona: int = 5,
             live_model: bool = False) -> EvalReport:
    if live_model and not configured():
        raise RuntimeError("LLM_MODEL is required for live evaluation")
    if games_per_persona < 1:
        raise ValueError("games_per_persona must be positive")
    run_id = uuid4().hex
    results = [simulate_game(script, store, persona, model_driven=live_model, variant=index)
               for persona in PERSONAS for index in range(games_per_persona)]
    probes = generate_probes(script)
    cases = []
    hits = 0
    if live_model:
        state = GameState(game_id=run_id, script_id=script.script_id,
                          act_id=script.acts[0].act_id,
                          seats={"seat_1": SeatState(seat_id="seat_1")})
        for index, probe in enumerate(probes):
            perception = build_perception(script, state, probe.role_id)
            reply, _ = respond(perception, probe.prompt, [], store, run_id)
            hit = not check_npc_output(script, perception, reply)
            if not hit:
                hit = not semantic_leak_check(script, reply, store, run_id)
            hits += hit
            cases.append({"case_id": f"probe_{index}", "input": probe.model_dump(),
                          "actual": {"reply": reply}, "category": probe.style, "hit": hit})
    judge_scores = []
    if live_model:
        for result in results:
            speech = next((event for event in store.events(result.game_id)
                           if event.type == EventType.NPC_SPEECH), None)
            if speech is None:
                continue
            role_id = speech.payload["role_id"]
            _, visible, perception = replay_at(script, store, result.game_id, speech.seq, role_id)
            knowledge = ([str(item) for item in perception.known_events + perception.known_clues]
                         if perception else [])
            dialogue = [event.payload.get("text", "") for event in visible
                        if event.type in (EventType.PLAYER_INPUT, EventType.NPC_SPEECH)][-8:]
            try:
                score = judge_response(store, result.game_id,
                                       script.characters[role_id].public_profile,
                                       knowledge, dialogue, speech.payload["text"])
                judge_scores.append(mean((score.in_character, score.consistent,
                                          score.grounded, score.natural)))
                cases.append({"case_id": f"judge_{result.game_id}",
                              "input": {"role_id": role_id, "seq": speech.seq},
                              "actual": score.model_dump(), "category": "judge", "hit": False})
            except Exception as exc:
                cases.append({"case_id": f"judge_{result.game_id}",
                              "input": {"role_id": role_id, "seq": speech.seq},
                              "actual": {"error": str(exc)}, "category": "judge", "hit": True})
    for result in results:
        for index, failure in enumerate(result.invariant_failures + result.errors):
            cases.append({"case_id": f"{result.game_id}_{index}", "input": {"persona": result.persona},
                          "actual": {"failure": failure}, "category": "invariant", "hit": True})
    ids = [result.game_id for result in results]
    traces = []
    with store.connect() as db:
        for game_id in [*ids, run_id]:
            traces.extend(dict(row) for row in db.execute("SELECT * FROM llm_traces WHERE game_id=?", (game_id,)))
    known_costs = [row["cost_usd"] for row in traces if row["cost_usd"] is not None]
    metrics = EvalMetrics(
        games=len(results), completed=sum(result.completed for result in results),
        win_rate=mean(result.win for result in results),
        stuck_rate=mean(result.stuck_level2 for result in results),
        leak_rate=hits / len(probes) if live_model and probes else None,
        mean_turns=mean(result.turns for result in results),
        invariant_failures=sum(len(result.invariant_failures) + len(result.errors) for result in results),
        model_evaluated=live_model,
        input_tokens=sum(row["input_tokens"] for row in traces),
        output_tokens=sum(row["output_tokens"] for row in traces),
        cost_usd=sum(known_costs) if known_costs else None,
        p95_latency_ms=p95([row["latency_ms"] for row in traces]),
        judge_mean=mean(judge_scores) if judge_scores else None,
    )
    gate_passed = (metrics.completed == metrics.games and metrics.invariant_failures == 0
                   and metrics.stuck_rate < 0.10
                   and all(result.proactive_count >= 2 for result in results)
                   and (not live_model or metrics.leak_rate < 0.05))
    limitations = []
    if not live_model:
        limitations.append("Offline run: model leak rate, judge quality and monetary cost not measured")
        limitations.append("Offline win rate uses a rotating scripted accusation, not evidence-based reasoning")
    if len(script.acts) == 1:
        limitations.append("Only one script and one act were exercised")
    if live_model:
        limitations.append("Judge scores are uncalibrated until paired human labels reach kappa >= 0.6")
    report = EvalReport(run_id=run_id, script_id=script.script_id, metrics=metrics,
                        results=results, probe_count=len(probes),
                        probe_hits=hits if live_model else None,
                        gate_passed=gate_passed, limitations=limitations)
    EvalStore(store).save_run(run_id, script.script_id,
                              {"games_per_persona": games_per_persona, "live_model": live_model},
                              metrics.model_dump(), "passed" if gate_passed else "failed", cases)
    return report


def render_report(report: EvalReport, title: str) -> str:
    metrics = report.metrics
    lines = [f"# 评测报告：{title}", f"- Run: {report.run_id}",
             f"- 剧本：{report.script_id}", f"- 对局：{metrics.games}，完成：{metrics.completed}",
             "", "| 指标 | 结果 |", "|---|---:|",
             f"| 通关率 | {metrics.win_rate:.1%} |",
             f"| 二级卡关率 | {metrics.stuck_rate:.1%} |",
             f"| 泄密率 | {f'{metrics.leak_rate:.1%}' if metrics.leak_rate is not None else '未测'} |",
             f"| 平均回合数 | {metrics.mean_turns:.1f} |",
             f"| 不变量失败 | {metrics.invariant_failures} |",
             f"| 输入/输出 token | {metrics.input_tokens}/{metrics.output_tokens} |",
             f"| p95 延迟 | {metrics.p95_latency_ms if metrics.p95_latency_ms is not None else '未测'} ms |",
             f"| 成本 | {metrics.cost_usd if metrics.cost_usd is not None else '未测'} USD |",
             f"| 抽样 judge 均分 | {metrics.judge_mean if metrics.judge_mean is not None else '未测'} |",
             "", f"探针数：{report.probe_count}；门禁：{'通过' if report.gate_passed else '失败'}。"]
    if report.limitations:
        lines.extend(["", "## 限制", *(f"- {item}" for item in report.limitations)])
    return "\n".join(lines) + "\n"
