import argparse
import json
from pathlib import Path

from jubensha.compiler.package import compile_package
from jubensha.storage.events import EventStore
from jubensha.storage.scripts import ScriptStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--names", nargs="*")
    parser.add_argument("--db", default="game_v2.db")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    folders = [path for path in args.root.iterdir() if path.is_dir()
               and path.name.startswith("MIRAGE_")
               and (not args.names or path.name.removeprefix("MIRAGE_") in args.names)]
    if not folders:
        parser.error("no script packages found")
    scripts = ScriptStore(EventStore(args.db)) if args.save else None
    for folder in sorted(folders):
        draft = compile_package(folder)
        if scripts:
            try:
                scripts.get_draft(draft.ir["script_id"])
            except KeyError:
                pass
            else:
                print(f"{folder.name}: skipped (draft already exists)")
                continue
            manifest = json.dumps({"files": draft.ir["parser_meta"]["source_files"]},
                                  ensure_ascii=False).encode("utf-8")
            upload_id = scripts.save_upload(folder.name + ".json", manifest,
                                            rights_source="local verification only",
                                            rights_confirmed=False,
                                            distribution_scope="local_only")
            try:
                scripts.save_draft(draft, upload_id)
            except ValueError as exc:
                print(f"{folder.name}: skipped ({exc})")
                continue
        print(json.dumps({"title": draft.ir["title"], "script_id": draft.ir["script_id"],
                          "roles": len(draft.ir["characters"]), "acts": len(draft.ir["acts"]),
                          "clues": len(draft.ir["clues"]), "source_chars": len(draft.source_text),
                          "blockers": len(draft.ir["linter_report"]["blockers"]),
                          "saved": bool(args.save)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
