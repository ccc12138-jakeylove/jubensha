import argparse
import json
import os
import subprocess
from pathlib import Path

from jubensha.eval.harness import render_report, run_eval
from jubensha.eval.calibration import manual_gate, read_labels
from jubensha.eval.metrics import EvalMetrics
from jubensha.eval.regression import regression_reasons
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixtures", nargs="+", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("eval_reports"))
    parser.add_argument("--games-per-persona", type=int, default=5)
    parser.add_argument("--judge-labels", type=Path)
    parser.add_argument("--probe-labels", type=Path)
    parser.add_argument("--npc-labels", type=Path)
    parser.add_argument("--model-only", action="store_true",
                        help="run model regression without claiming full V2 acceptance")
    args = parser.parse_args()
    if len(args.fixtures) != 3 or len({path.resolve() for path in args.fixtures}) != 3:
        parser.error("V2 gate requires three distinct complete scripts")
    if not os.getenv("LLM_MODEL"):
        parser.error("LLM_MODEL is required for the V2 model gate")
    if not args.model_only and not all((args.judge_labels, args.probe_labels, args.npc_labels)):
        parser.error("human judge, probe and NPC labels are required for V2 acceptance")
    scripts = [Script.model_validate_json(path.read_text(encoding="utf-8")) for path in args.fixtures]
    if len({script.script_id for script in scripts}) != 3:
        parser.error("V2 gate requires three distinct script IDs")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else {}
    if "reports" in baseline:
        baseline = {item["script_id"]: item | {"model": baseline.get("model")}
                    for item in baseline["reports"]}
    git_sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.strip()
    store = EventStore(os.getenv("GAME_DB", "eval_gate.db"))
    summaries = []
    passed = True
    expected_probes = 0
    for index, script in enumerate(scripts, 1):
        report = run_eval(script, store, games_per_persona=args.games_per_persona,
                          live_model=True)
        (args.output_dir / f"script_{index}.md").write_text(
            render_report(report, script.title), encoding="utf-8")
        reasons = []
        if script.script_id in baseline:
            prior = baseline[script.script_id]
            if prior.get("ir_sha256") != report.ir_sha256:
                reasons.append("IR fingerprint changed since baseline")
            elif prior.get("model") != report.model_name:
                reasons.append("model changed since baseline")
            else:
                reasons = regression_reasons(report.metrics,
                                             EvalMetrics.model_validate(prior["metrics"]))
        passed = passed and report.gate_passed and not reasons
        expected_probes += report.probe_count
        summaries.append({"script_id": script.script_id, "run_id": report.run_id,
                          "metrics": report.metrics.model_dump(), "gate_passed": report.gate_passed,
                          "regressions": reasons, "ir_sha256": report.ir_sha256})
    manual = (manual_gate(read_labels(args.judge_labels), read_labels(args.probe_labels),
                          read_labels(args.npc_labels), expected_probes)
              if not args.model_only else None)
    passed = passed and (manual["passed"] if manual is not None else True)
    manifest = {"git_sha": git_sha, "model": os.environ["LLM_MODEL"],
                "games_per_persona": args.games_per_persona,
                "model_gate_passed": passed if args.model_only else all(
                    item["gate_passed"] and not item["regressions"] for item in summaries),
                "v2_acceptance_passed": passed if manual is not None else False,
                "manual": manual, "reports": summaries}
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": passed, "output": str(args.output_dir)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
