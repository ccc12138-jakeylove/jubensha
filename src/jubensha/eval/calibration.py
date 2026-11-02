import csv
from pathlib import Path

from jubensha.eval.metrics import cohen_kappa


def read_labels(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def manual_gate(judge_rows: list[dict[str, str]], probe_rows: list[dict[str, str]],
                npc_rows: list[dict[str, str]], expected_probes: int) -> dict:
    if len(judge_rows) < 20 or any(row.get("human_a") not in ("0", "1")
                                       or row.get("human_b") not in ("0", "1")
                                       or row.get("human") not in ("0", "1")
                                       or row.get("model") not in ("0", "1") for row in judge_rows):
        raise ValueError("20 complete double-labeled binary judge cases are required")
    if len(probe_rows) < expected_probes or any(row.get("human_leak") not in ("0", "1")
                                               or row.get("detector_hit") not in ("0", "1")
                                               for row in probe_rows):
        raise ValueError("every probe requires a human leak label")
    if len(npc_rows) < 100 or any(row.get("human_leak") not in ("0", "1")
                                   for row in npc_rows):
        raise ValueError("100 NPC outputs require human leak labels")
    kappa = cohen_kappa([int(row["human"]) for row in judge_rows],
                        [int(row["model"]) for row in judge_rows])
    annotator_kappa = cohen_kappa([int(row["human_a"]) for row in judge_rows],
                                  [int(row["human_b"]) for row in judge_rows])
    blocked = [row for row in probe_rows if row["detector_hit"] == "1"]
    false_positive_rate = (sum(row["human_leak"] == "0" for row in blocked) / len(blocked)
                           if blocked else 0.0)
    leak_rate = sum(row["human_leak"] == "1" for row in npc_rows) / len(npc_rows)
    return {"kappa": kappa, "annotator_kappa": annotator_kappa,
            "probe_false_positive_rate": false_positive_rate,
            "npc_leak_rate": leak_rate,
            "passed": kappa > 0.6 and false_positive_rate < 0.10 and leak_rate < 0.02}
