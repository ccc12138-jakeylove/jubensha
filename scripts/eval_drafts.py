import argparse
import json
from pathlib import Path

from jubensha.eval.harness import render_report, run_eval
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore
from jubensha.storage.scripts import ScriptStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("script_ids", nargs="+")
    parser.add_argument("--draft-db", default="game_v2.db")
    parser.add_argument("--eval-db", default="eval_drafts.db")
    parser.add_argument("--games-per-persona", type=int, default=1)
    parser.add_argument("--live-model", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("local_reviews/evals"))
    args = parser.parse_args()
    drafts = ScriptStore(EventStore(args.draft_db))
    events = EventStore(args.eval_db)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for script_id in args.script_ids:
        script = Script.model_validate(drafts.get_draft(script_id)["ir"])
        report = run_eval(script, events, games_per_persona=args.games_per_persona,
                          live_model=args.live_model)
        (args.output_dir / f"{script_id}.md").write_text(
            render_report(report, script.title), encoding="utf-8")
        print(json.dumps({"script_id": script_id, "games": report.metrics.games,
                          "completed": report.metrics.completed,
                          "win_rate": report.metrics.win_rate,
                          "invariant_failures": report.metrics.invariant_failures,
                          "structural_passed" if not args.live_model else "model_gate_passed":
                          report.gate_passed}, ensure_ascii=False))


if __name__ == "__main__":
    main()
