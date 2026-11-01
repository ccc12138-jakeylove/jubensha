import argparse
import csv
import json
from pathlib import Path

from jubensha.storage.events import EventStore
from jubensha.storage.evals import EvalStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--db", default="eval_acceptance4b.db")
    parser.add_argument("--judge-output", default="judge_review.csv")
    parser.add_argument("--probe-output", default="probe_review.csv")
    args = parser.parse_args()
    events = EventStore(args.db)
    cases = EvalStore(events).cases(args.run_id)
    judge_rows = []
    probe_rows = []
    for case in cases:
        source = json.loads(case["input_json"])
        actual = json.loads(case["actual_json"])
        if case["category"] == "judge" and "consistent" in actual:
            game_id = case["case_id"].removeprefix("judge_")
            history = events.events(game_id)
            speech = next((event for event in history if event.seq == source["seq"]), None)
            preceding = [event.payload.get("text", "") for event in history
                         if event.seq < source["seq"] and event.type.value == "player_input"]
            judge_rows.append({"case_id": case["case_id"], "role_id": source["role_id"],
                               "question": preceding[-1] if preceding else "",
                               "reply": speech.payload.get("text", "") if speech else "",
                               "model_score": actual["consistent"],
                               "model": int(actual["consistent"] >= 4), "human": ""})
        elif case["case_id"].startswith("probe_"):
            probe_rows.append({"case_id": case["case_id"], "role_id": source["role_id"],
                               "target": source["target"], "style": source["style"],
                               "question": source["prompt"], "reply": actual.get("reply", ""),
                               "detector_hit": case["hit"], "human_leak": ""})
    for path, rows, fields in (
        (args.judge_output, judge_rows,
         ["case_id", "role_id", "question", "reply", "model_score", "model", "human"]),
        (args.probe_output, probe_rows,
         ["case_id", "role_id", "target", "style", "question", "reply", "detector_hit", "human_leak"]),
    ):
        with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    print(f"judge={len(judge_rows)} probe={len(probe_rows)}")


if __name__ == "__main__":
    main()
