import argparse
import csv
import json
from pathlib import Path

from jubensha.schema.events import EventType
from jubensha.storage.events import EventStore
from jubensha.storage.scripts import ScriptStore


CHECKS = (
    "真凶身份", "作案动机", "关键物证", "事件时间线", "线索开放幕次",
    "公开剧情", "角色认知边界", "秘密泄露边界", "投票胜利条件", "内容分级",
)


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("game_ids", nargs="+")
    parser.add_argument("--output", type=Path, default=Path("local_reviews/review_packet.json"))
    parser.add_argument("--historical-root", type=Path)
    args = parser.parse_args()

    store = EventStore()
    scripts = ScriptStore(store)
    current_npc = []
    for game_id in args.game_ids:
        draft = scripts.get_draft(store.game_script_id(game_id))
        names = {key: item["display_name"] for key, item in draft["ir"]["characters"].items()}
        question = ""
        for event in store.events(game_id):
            if event.type == EventType.PLAYER_INPUT:
                question = event.payload.get("text", "")
            elif event.type == EventType.NPC_SPEECH:
                current_npc.append({
                    "case_id": f"{game_id}:{event.seq}", "script": draft["title"],
                    "role": names.get(event.payload.get("role_id"), ""),
                    "question": question, "reply": event.payload.get("text", ""),
                    "evidence_ids": ",".join(event.payload.get("evidence_ids", [])),
                    "model": "qwen3.7-plus", "human_leak": "", "notes": "",
                })

    author_checks = [{"script": "雾港谜案", "source": "fixtures/wugang_01.json",
                      "field": check, "review_prompt": f"核对{check}是否与原剧本一致",
                      "accurate": "", "notes": ""} for check in CHECKS]
    for script_id in ("package_cbee32a78c47", "package_19ecfed1dcf2"):
        draft = scripts.get_draft(script_id)
        reviews = [(item, resolved) for _, item, resolved in scripts.reviews(script_id)]
        for item, resolved in reviews:
            if resolved or len([row for row in author_checks if row["script"] == draft["title"]]) >= 10:
                continue
            author_checks.append({"script": draft["title"],
                                  "source": draft["source_filename"],
                                  "field": item.field_path,
                                  "review_prompt": item.message,
                                  "accurate": "", "notes": ""})

    historical = {}
    if args.historical_root:
        for kind in ("judge", "probe", "npc"):
            historical[kind] = read_csv(args.historical_root / f"oriental_{kind}_review_v6.csv")

    result = {"current_npc": current_npc, "author_checks": author_checks,
              "historical": historical,
              "status": "preliminary: current target model samples are below formal V2 quotas"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"current_npc": len(current_npc), "author_checks": len(author_checks),
                      "historical": {key: len(rows) for key, rows in historical.items()}},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
