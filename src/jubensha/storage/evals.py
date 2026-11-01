import json

from jubensha.storage.events import EventStore


class EvalStore:
    def __init__(self, events: EventStore):
        self.events = events
        with events.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS eval_runs (
                    run_id TEXT PRIMARY KEY, script_id TEXT NOT NULL,
                    config_json TEXT NOT NULL, metrics_json TEXT NOT NULL,
                    status TEXT NOT NULL, results_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS eval_cases (
                    run_id TEXT NOT NULL, case_id TEXT NOT NULL,
                    input_json TEXT NOT NULL, actual_json TEXT NOT NULL,
                    category TEXT NOT NULL, hit INTEGER NOT NULL,
                    PRIMARY KEY (run_id, case_id)
                );
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(eval_runs)")}
            if "results_json" not in columns:
                db.execute("ALTER TABLE eval_runs ADD COLUMN results_json TEXT NOT NULL DEFAULT '[]'")

    def save_run(self, run_id: str, script_id: str, config: dict, metrics: dict,
                 status: str, cases: list[dict], results: list[dict] | None = None) -> None:
        with self.events.connect() as db:
            db.execute("INSERT INTO eval_runs (run_id,script_id,config_json,metrics_json,status,results_json) VALUES (?,?,?,?,?,?)",
                       (run_id, script_id, json.dumps(config, ensure_ascii=False),
                        json.dumps(metrics, ensure_ascii=False), status,
                        json.dumps(results or [], ensure_ascii=False)))
            for case in cases:
                db.execute("INSERT INTO eval_cases VALUES (?,?,?,?,?,?)",
                           (run_id, case["case_id"], json.dumps(case["input"], ensure_ascii=False),
                            json.dumps(case["actual"], ensure_ascii=False), case["category"], int(case["hit"])))

    def list_runs(self, script_id: str | None = None) -> list[dict]:
        with self.events.connect() as db:
            if script_id:
                rows = db.execute("SELECT * FROM eval_runs WHERE script_id=? ORDER BY created_at DESC", (script_id,))
            else:
                rows = db.execute("SELECT * FROM eval_runs ORDER BY created_at DESC")
            return [dict(row) for row in rows]

    def cases(self, run_id: str) -> list[dict]:
        with self.events.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM eval_cases WHERE run_id=? ORDER BY case_id",
                                                    (run_id,))]
