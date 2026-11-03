import json

from jubensha.storage.events import EventStore


class EvalStore:
    def __init__(self, events: EventStore):
        self.events = events

    def save_run(self, run_id: str, script_id: str, config: dict, metrics: dict,
                 status: str, cases: list[dict], results: list[dict] | None = None) -> None:
        with self.events.connect() as db:
            db.execute(
                "INSERT INTO eval_runs (run_id,script_id,config_json,metrics_json,status,results_json) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (run_id, script_id, json.dumps(config, ensure_ascii=False),
                 json.dumps(metrics, ensure_ascii=False), status,
                 json.dumps(results or [], ensure_ascii=False)))
            for case in cases:
                db.execute("INSERT INTO eval_cases VALUES (%s,%s,%s,%s,%s,%s)",
                           (run_id, case["case_id"], json.dumps(case["input"], ensure_ascii=False),
                            json.dumps(case["actual"], ensure_ascii=False), case["category"], int(case["hit"])))
            for result in results or []:
                for category in result.get("attributions", []):
                    db.execute(
                        "INSERT INTO eval_attributions (run_id,game_id,category,detail) "
                        "VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (run_id, result["game_id"], category,
                         json.dumps(result.get("judgment_outcomes", {}), ensure_ascii=False)))

    def list_runs(self, script_id: str | None = None) -> list[dict]:
        with self.events.connect() as db:
            if script_id:
                rows = db.execute("SELECT * FROM eval_runs WHERE script_id=%s ORDER BY created_at DESC",
                                  (script_id,))
            else:
                rows = db.execute("SELECT * FROM eval_runs ORDER BY created_at DESC")
            return [dict(row) for row in rows]

    def cases(self, run_id: str) -> list[dict]:
        with self.events.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM eval_cases WHERE run_id=%s ORDER BY case_id", (run_id,))]
