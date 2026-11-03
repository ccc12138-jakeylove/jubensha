import argparse
import json
from pathlib import Path

from jubensha.compiler.package import compile_package, merge_statement_candidates
from jubensha.storage.events import EventStore
from jubensha.storage.scripts import ScriptStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--db", default="game_v2.db")
    args = parser.parse_args()
    scripts = ScriptStore(EventStore(args.db))
    for folder in sorted(args.root.glob("MIRAGE_*")):
        if not folder.is_dir():
            continue
        extracted = compile_package(folder)
        script_id = extracted.ir["script_id"]
        try:
            current = scripts.get_draft(script_id)
        except KeyError:
            continue
        updated = merge_statement_candidates(current["ir"], extracted.ir)
        scripts.update_ir(script_id, json.dumps(updated, ensure_ascii=False))
        print(f"{extracted.ir['title']}: {sum(len(item['statements']) for item in updated['knowledge'].values())} candidate statements")


if __name__ == "__main__":
    main()
