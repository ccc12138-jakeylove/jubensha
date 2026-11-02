import json
import sqlite3
from uuid import uuid4

from jubensha.storage.events import EventStore


class CompileJobs:
    def __init__(self, events: EventStore):
        self.events = events
        with events.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS compile_jobs (
                    job_id TEXT PRIMARY KEY, upload_id TEXT NOT NULL,
                    status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                    script_id TEXT, error TEXT, idempotency_key TEXT UNIQUE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP, finished_at TEXT
                )
            """)
            db.execute("UPDATE compile_jobs SET status='queued',progress=0 WHERE status='running'")

    def create(self, upload_id: str, idempotency_key: str | None = None) -> dict:
        job_id = uuid4().hex
        with self.events.connect() as db:
            try:
                db.execute("INSERT INTO compile_jobs (job_id,upload_id,status,idempotency_key) VALUES (?,?,'queued',?)",
                           (job_id, upload_id, idempotency_key))
            except sqlite3.IntegrityError:
                if not idempotency_key:
                    raise
                row = db.execute("SELECT * FROM compile_jobs WHERE idempotency_key=?",
                                 (idempotency_key,)).fetchone()
                if row["upload_id"] != upload_id:
                    raise ValueError("idempotency key was used for a different upload") from None
                return dict(row)
        return self.get(job_id)

    def get(self, job_id: str) -> dict:
        with self.events.connect() as db:
            row = db.execute("SELECT * FROM compile_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def claim_next(self) -> dict | None:
        with self.events.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM compile_jobs WHERE status='queued' ORDER BY created_at, rowid LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE compile_jobs SET status='running',progress=10 WHERE job_id=?",
                       (row["job_id"],))
            return dict(row)

    def finish(self, job_id: str, script_id: str | None = None, error: str | None = None) -> None:
        with self.events.connect() as db:
            db.execute("UPDATE compile_jobs SET status=?,progress=100,script_id=?,error=?,finished_at=CURRENT_TIMESTAMP WHERE job_id=?",
                       ("failed" if error else "completed", script_id, error, job_id))

    def retry(self, job_id: str) -> dict:
        self.get(job_id)
        with self.events.connect() as db:
            cursor = db.execute("UPDATE compile_jobs SET status='queued',progress=0,error=NULL,finished_at=NULL WHERE job_id=? AND status='failed'",
                                (job_id,))
            if cursor.rowcount != 1:
                raise ValueError("only failed compile jobs can be retried")
        return self.get(job_id)


class EvalJobs:
    def __init__(self, events: EventStore):
        self.events = events
        with events.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS eval_jobs (
                    job_id TEXT PRIMARY KEY, script_id TEXT NOT NULL,
                    games_per_persona INTEGER NOT NULL, live_model INTEGER NOT NULL,
                    status TEXT NOT NULL, run_id TEXT, metrics_json TEXT,
                    error TEXT, idempotency_key TEXT UNIQUE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP, finished_at TEXT
                )
            """)
            db.execute("UPDATE eval_jobs SET status='queued' WHERE status='running'")

    def create(self, script_id: str, games_per_persona: int, live_model: bool,
               idempotency_key: str | None = None) -> dict:
        job_id = uuid4().hex
        with self.events.connect() as db:
            try:
                db.execute("INSERT INTO eval_jobs (job_id,script_id,games_per_persona,live_model,status,idempotency_key) VALUES (?,?,?,?,'queued',?)",
                           (job_id, script_id, games_per_persona, int(live_model), idempotency_key))
            except sqlite3.IntegrityError:
                if not idempotency_key:
                    raise
                row = db.execute("SELECT * FROM eval_jobs WHERE idempotency_key=?",
                                 (idempotency_key,)).fetchone()
                if (row["script_id"], row["games_per_persona"], row["live_model"]) != (
                        script_id, games_per_persona, int(live_model)):
                    raise ValueError("idempotency key was used for a different evaluation") from None
                return self.get(row["job_id"])
        return self.get(job_id)

    def get(self, job_id: str) -> dict:
        with self.events.connect() as db:
            row = db.execute("SELECT * FROM eval_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        result = dict(row)
        result["metrics"] = json.loads(result.pop("metrics_json")) if result["metrics_json"] else None
        return result

    def list_jobs(self, script_id: str, limit: int = 10) -> list[dict]:
        with self.events.connect() as db:
            ids = [row[0] for row in db.execute(
                "SELECT job_id FROM eval_jobs WHERE script_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?",
                (script_id, limit))]
        return [self.get(job_id) for job_id in ids]

    def claim_next(self) -> dict | None:
        with self.events.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM eval_jobs WHERE status='queued' ORDER BY created_at,rowid LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE eval_jobs SET status='running' WHERE job_id=?", (row["job_id"],))
            return dict(row)

    def finish(self, job_id: str, run_id: str | None = None,
               metrics: dict | None = None, error: str | None = None) -> None:
        with self.events.connect() as db:
            db.execute("UPDATE eval_jobs SET status=?,run_id=?,metrics_json=?,error=?,finished_at=CURRENT_TIMESTAMP WHERE job_id=?",
                       ("failed" if error else "completed", run_id,
                        json.dumps(metrics, ensure_ascii=False) if metrics else None, error, job_id))

    def retry(self, job_id: str) -> dict:
        self.get(job_id)
        with self.events.connect() as db:
            cursor = db.execute("UPDATE eval_jobs SET status='queued',error=NULL,finished_at=NULL WHERE job_id=? AND status='failed'",
                                (job_id,))
            if cursor.rowcount != 1:
                raise ValueError("only failed evaluation jobs can be retried")
        return self.get(job_id)
