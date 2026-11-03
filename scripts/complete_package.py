import argparse
import json
from pathlib import Path

from jubensha.compiler.package import apply_review
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore
from jubensha.storage.scripts import ScriptStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("review", type=Path)
    parser.add_argument("--db", default="game_v2.db")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    review = json.loads(args.review.read_text(encoding="utf-8"))
    scripts = ScriptStore(EventStore(args.db))
    draft = scripts.get_draft(review["script_id"])
    ir = apply_review(draft["ir"], review, draft["source_text"])
    report = Script.model_validate(ir).linter_report
    print(json.dumps({"script_id": ir["script_id"], "passed": report.passed,
                      "blockers": [item.model_dump() for item in report.blockers],
                      "warnings": len(report.warnings)}, ensure_ascii=False))
    if args.save:
        scripts.update_ir(ir["script_id"], json.dumps(ir, ensure_ascii=False))


if __name__ == "__main__":
    main()
