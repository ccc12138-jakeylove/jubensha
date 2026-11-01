import argparse
import json
import os
from pathlib import Path

from jubensha.eval.harness import render_report, run_eval
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default=os.getenv("SCRIPT_FIXTURE", "fixtures/wugang_01.json"))
    parser.add_argument("--games-per-persona", type=int, default=5)
    parser.add_argument("--live-model", action="store_true")
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--output", default="eval_report.md")
    args = parser.parse_args()
    if args.temperature is not None:
        os.environ["LLM_TEMPERATURE"] = str(args.temperature)
    script = Script.model_validate_json(Path(args.fixture).read_text(encoding="utf-8"))
    store = EventStore(os.getenv("GAME_DB", "game.db"))
    report = run_eval(script, store, games_per_persona=args.games_per_persona,
                      live_model=args.live_model)
    Path(args.output).write_text(render_report(report, script.title), encoding="utf-8")
    print(json.dumps({"run_id": report.run_id, "games": report.metrics.games,
                      "completed": report.metrics.completed,
                      "stuck_rate": report.metrics.stuck_rate,
                      "invariant_failures": report.metrics.invariant_failures,
                      "gate_passed": report.gate_passed,
                      "report": args.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
