from statistics import mean
import json
from uuid import uuid4
from difflib import SequenceMatcher
import re
import os
import subprocess
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from jubensha.agents.judge import judge_response
from jubensha.engine.guard import check_npc_output
from jubensha.engine.loop import build_turn_graph, run_turn
from jubensha.engine.perception import build_perception
from jubensha.engine.probes import generate_probes
from jubensha.engine.replay import replay_at
from jubensha.eval.metrics import EvalMetrics, p95
from jubensha.eval.simulator import PERSONAS, SimResult, simulate_game
from jubensha.llm.gateway import configured
from jubensha.schema.ir import Script
from jubensha.schema.events import EventType
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
    model_name: str
    temperature: float
    ir_sha256: str
    git_sha: str = ""
    prompt_hash: str = ""
    model_routes: dict[str, str] = Field(default_factory=dict)


def _probe_hit(forbidden_surfaces: list[str], reply: str) -> bool:
    answer = "".join(re.findall(r"[\w\u4e00-\u9fff]+", reply.lower()))
    for surface in forbidden_surfaces:
        phrase = "".join(re.findall(r"[\w\u4e00-\u9fff]+", surface.lower()))
        if len(phrase) < 6:
            continue
        if phrase in answer:
            return True
        if len(answer) >= len(phrase) and any(
            SequenceMatcher(None, phrase, answer[start:start + len(phrase)]).ratio() >= 0.88
            for start in range(len(answer) - len(phrase) + 1)):
            return True
    return False


def _prompt_code_hash() -> str:
    root = Path(__file__).resolve().parents[1]
    files = ("agents/npc.py", "agents/judge.py", "engine/guard.py",
             "compiler/pipeline.py", "eval/simulator.py")
    digest = sha256()
    for name in files:
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


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
    raw_hits = 0
    probe_game_ids = []
    if live_model:
        for index, probe in enumerate(probes):
            probe_game_id = uuid4().hex
            probe_game_ids.append(probe_game_id)
            store.create_game(probe_game_id, script.script_id, script.acts[0].act_id)
            graph = build_turn_graph(script, store)
            try:
                for action in ("begin", "read_done"):
                    run_turn(graph, store, script, {"game_id": probe_game_id, "action": action})
                result = run_turn(graph, store, script, {"game_id": probe_game_id,
                                                        "action": "talk", "role_id": probe.role_id,
                                                        "text": probe.prompt})
                spoken = next(event for event in store.events(probe_game_id)
                              if event.type == EventType.NPC_SPEECH
                              and event.payload.get("role_id") == probe.role_id)
                reply = spoken.payload["text"]
                perception = build_perception(script, store.load(probe_game_id,
                                                               script.acts[0].search_points_budget), probe.role_id)
                hit = (_probe_hit(probe.forbidden_surfaces, reply)
                       or not check_npc_output(script, perception, reply, probe.prompt))
                raw_hit = bool(result.get("leak_blocked"))
            except Exception as exc:
                reply = f"ERROR: {exc}"
                hit = True
                raw_hit = True
            hits += hit
            raw_hits += raw_hit
            cases.append({"case_id": f"probe_{index}", "input": probe.model_dump(),
                          "actual": {"reply": reply, "guard_blocked": raw_hit,
                                     "blocked_candidates": [
                                         {"candidate": item["candidate"], "reason": item["reason"]}
                                         for item in store.guard_cases(probe_game_id)
                                         if item["role_id"] == probe.role_id]},
                          "category": probe.style, "hit": hit})
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
    ids = [result.game_id for result in results] + probe_game_ids
    traces = []
    with store.connect() as db:
        for game_id in [*ids, run_id]:
            traces.extend(dict(row) for row in db.execute("SELECT * FROM llm_traces WHERE game_id=?", (game_id,)))
    known_costs = [row["cost_usd"] for row in traces if row["cost_usd"] is not None]
    metrics = EvalMetrics(
        games=len(results), completed=sum(result.completed for result in results),
        win_rate=mean(result.win for result in results),
        normal_win_rate=mean(result.win for result in results if result.persona != "meta"),
        culprit_rate=mean(result.culprit_correct for result in results),
        stuck_rate=mean(result.stuck_level2 for result in results),
        leak_rate=hits / len(probes) if live_model and probes else None,
        raw_risk_rate=raw_hits / len(probes) if live_model and probes else None,
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
                   and (not live_model or (games_per_persona >= 5
                                           and metrics.normal_win_rate >= 0.80
                                           and metrics.leak_rate < 0.05)))
    limitations = []
    if not live_model:
        limitations.append("Offline run: model leak rate, judge quality and monetary cost not measured")
        limitations.append("Offline win rate uses a rotating scripted accusation, not evidence-based reasoning")
    if len(script.acts) == 1:
        limitations.append("Only one script and one act were exercised")
    if live_model:
        if games_per_persona < 5:
            limitations.append("Fewer than 20 games: this is a smoke test, not the V1 model acceptance gate")
        limitations.append("Judge scores are uncalibrated until paired human labels reach kappa >= 0.6")
        limitations.append("Final probe hits use a separate lexical check, but semantic leakage still needs independent human review")
    report = EvalReport(run_id=run_id, script_id=script.script_id, metrics=metrics,
                        results=results, probe_count=len(probes),
                        probe_hits=hits if live_model else None,
                        gate_passed=gate_passed, limitations=limitations,
                        model_name=os.getenv("LLM_MODEL", "offline"),
                        temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
                        ir_sha256=sha256(script.model_dump_json().encode("utf-8")).hexdigest(),
                        git_sha=subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                               text=True, check=False).stdout.strip(),
                        prompt_hash=_prompt_code_hash(),
                        model_routes={key: value for key in (
                            "LLM_MODEL_COMPILER", "LLM_MODEL_STRONG", "LLM_MODEL_NPC",
                            "LLM_MODEL_JUDGE", "LLM_MODEL_SIMULATOR", "LLM_MODEL_GUARD")
                            if (value := os.getenv(key))})
    EvalStore(store).save_run(run_id, script.script_id,
                              {"games_per_persona": games_per_persona, "live_model": live_model,
                               "model_name": report.model_name,
                               "temperature": report.temperature,
                               "ir_sha256": report.ir_sha256,
                               "git_sha": report.git_sha,
                               "prompt_hash": report.prompt_hash,
                               "model_routes": report.model_routes},
                              metrics.model_dump(), "passed" if gate_passed else "failed", cases,
                              [result.model_dump() for result in results])
    return report


def render_report(report: EvalReport, title: str) -> str:
    metrics = report.metrics
    lines = [f"# 评测报告：{title}", f"- Run: {report.run_id}",
             f"- 剧本：{report.script_id}", f"- 对局：{metrics.games}，完成：{metrics.completed}",
             f"- 模型：{report.model_name}，temperature={report.temperature:g}",
             f"- 模型路由：{json.dumps(report.model_routes, ensure_ascii=False) if report.model_routes else '默认模型'}",
             f"- IR SHA256：{report.ir_sha256}",
             f"- Git SHA：{report.git_sha or '未知'}",
             f"- Prompt 代码 SHA256：{report.prompt_hash}",
             "", "| 指标 | 结果 |", "|---|---:|",
             f"| 完整通关率 | {metrics.win_rate:.1%} |",
             f"| 正常策略通关率（不含元攻击） | {metrics.normal_win_rate:.1%} |",
             f"| 凶手指认率 | {metrics.culprit_rate:.1%} |",
             f"| 二级卡关率 | {metrics.stuck_rate:.1%} |",
             f"| 最终回复探针命中率 | {f'{metrics.leak_rate:.1%}' if metrics.leak_rate is not None else '未测'} |",
             f"| 输出闸拦截率 | {f'{metrics.raw_risk_rate:.1%}' if metrics.raw_risk_rate is not None else '未测'} |",
             f"| 平均回合数 | {metrics.mean_turns:.1f} |",
             f"| 不变量失败 | {metrics.invariant_failures} |",
             f"| 输入/输出 token | {metrics.input_tokens}/{metrics.output_tokens} |",
             f"| p95 延迟 | {metrics.p95_latency_ms if metrics.p95_latency_ms is not None else '未测'} ms |",
             f"| 成本 | {metrics.cost_usd if metrics.cost_usd is not None else '未测'} USD |",
             f"| 抽样 judge 均分 | {metrics.judge_mean if metrics.judge_mean is not None else '未测'} |",
             "", f"探针数：{report.probe_count}；工程门禁：{'通过' if report.gate_passed else '失败'}；模型质量验收：{'待人工校准' if metrics.model_evaluated else '未测'}。"]
    lines.extend(["", "| 策略 | 局数 | 通关 | 主动发言不足两次 |",
                  "|---|---:|---:|---:|"])
    for persona in PERSONAS:
        group = [result for result in report.results if result.persona == persona]
        lines.append(f"| {persona} | {len(group)} | {sum(item.win for item in group)} | "
                     f"{sum(item.proactive_count < 2 for item in group)} |")
    if report.limitations:
        lines.extend(["", "## 限制", *(f"- {item}" for item in report.limitations)])
    return "\n".join(lines) + "\n"
