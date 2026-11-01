import json
from uuid import uuid4

from jubensha.compiler.lint import lint_script
from jubensha.compiler.pipeline import CompilationDraft, ReviewItem
from jubensha.schema.ir import Script
from jubensha.agents.referee import profile_for
from jubensha.storage.events import EventStore


class ScriptStore:
    def __init__(self, events: EventStore):
        self.events = events
        with events.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS scripts (
                    script_id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
                    source_filename TEXT NOT NULL, source_text TEXT NOT NULL, ir_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS script_uploads (
                    upload_id TEXT PRIMARY KEY, filename TEXT NOT NULL,
                    content BLOB NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS script_versions (
                    script_id TEXT NOT NULL, version TEXT NOT NULL, ir_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (script_id, version)
                );
                CREATE TABLE IF NOT EXISTS review_items (
                    item_id INTEGER PRIMARY KEY AUTOINCREMENT, script_id TEXT NOT NULL,
                    item_json TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0
                );
            """)

    def register_fixture(self, script: Script) -> None:
        with self.events.connect() as db:
            db.execute("INSERT OR IGNORE INTO scripts (script_id,title,status,source_filename,source_text,ir_json) VALUES (?,?,?,?,?,?)",
                       (script.script_id, script.title, "published", "builtin fixture", "",
                        script.model_dump_json()))
            db.execute("INSERT OR IGNORE INTO script_versions VALUES (?,?,?,CURRENT_TIMESTAMP)",
                       (script.script_id, script.ir_version, script.model_dump_json()))

    def save_upload(self, filename: str, content: bytes) -> str:
        upload_id = uuid4().hex
        with self.events.connect() as db:
            db.execute("INSERT INTO script_uploads (upload_id,filename,content) VALUES (?,?,?)",
                       (upload_id, filename, content))
        return upload_id

    def get_upload(self, upload_id: str) -> tuple[str, bytes]:
        with self.events.connect() as db:
            row = db.execute("SELECT filename,content FROM script_uploads WHERE upload_id=?",
                             (upload_id,)).fetchone()
        if row is None:
            raise KeyError(upload_id)
        return row["filename"], row["content"]

    def save_draft(self, draft: CompilationDraft) -> str:
        script_id = str(draft.ir.get("script_id") or f"draft_{uuid4().hex}")
        draft.ir["script_id"] = script_id
        title = str(draft.ir.get("title") or draft.filename)
        with self.events.connect() as db:
            if db.execute("SELECT 1 FROM scripts WHERE script_id=?", (script_id,)).fetchone():
                raise ValueError("script_id already exists; edit the existing draft")
            db.execute("INSERT INTO scripts (script_id,title,status,source_filename,source_text,ir_json) VALUES (?,?,?,?,?,?)",
                       (script_id, title, "draft", draft.filename, draft.source_text,
                        json.dumps(draft.ir, ensure_ascii=False)))
            for item in draft.review_items:
                db.execute("INSERT INTO review_items (script_id,item_json,resolved) VALUES (?,?,?)",
                           (script_id, item.model_dump_json(), int(item.resolved)))
        return script_id

    def list_scripts(self) -> list[dict]:
        with self.events.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT script_id,title,status,source_filename,created_at FROM scripts ORDER BY created_at DESC")]

    def get_draft(self, script_id: str) -> dict:
        with self.events.connect() as db:
            row = db.execute("SELECT * FROM scripts WHERE script_id=?", (script_id,)).fetchone()
            if row is None:
                raise KeyError(script_id)
            return dict(row) | {"ir": json.loads(row["ir_json"])}

    def reviews(self, script_id: str) -> list[tuple[int, ReviewItem, bool]]:
        with self.events.connect() as db:
            return [(row["item_id"], ReviewItem.model_validate_json(row["item_json"]), bool(row["resolved"]))
                    for row in db.execute("SELECT * FROM review_items WHERE script_id=? ORDER BY item_id", (script_id,))]

    def resolve(self, script_id: str, item_id: int) -> None:
        with self.events.connect() as db:
            cursor = db.execute("UPDATE review_items SET resolved=1 WHERE script_id=? AND item_id=?",
                                (script_id, item_id))
            if cursor.rowcount != 1:
                raise KeyError(item_id)

    def update_ir(self, script_id: str, raw_json: str) -> None:
        draft = self.get_draft(script_id)
        if draft["status"] != "draft":
            raise ValueError("published scripts are immutable")
        parsed = json.loads(raw_json)
        script = Script.model_validate(parsed)
        if script.script_id != script_id:
            raise ValueError("script_id cannot change during review")
        report = lint_script(script)
        parsed["linter_report"] = report.model_dump()
        with self.events.connect() as db:
            db.execute("UPDATE scripts SET ir_json=?,title=? WHERE script_id=?",
                       (json.dumps(parsed, ensure_ascii=False), script.title, script_id))
            db.execute("DELETE FROM review_items WHERE script_id=? AND json_extract(item_json, '$.conflict_type') IN ('script_bug','linter_warning')",
                       (script_id,))
            for issue in report.blockers:
                item = ReviewItem(field_path=issue.target_id, confidence=0,
                                  conflict_type="script_bug", message=issue.message)
                db.execute("INSERT INTO review_items (script_id,item_json,resolved) VALUES (?,?,0)",
                           (script_id, item.model_dump_json()))
            for issue in report.warnings:
                if issue.severity == "high":
                    item = ReviewItem(field_path=issue.target_id, confidence=0.5,
                                      conflict_type="linter_warning", message=issue.message)
                    db.execute("INSERT INTO review_items (script_id,item_json,resolved) VALUES (?,?,0)",
                               (script_id, item.model_dump_json()))

    def publish(self, script_id: str) -> Script:
        draft = self.get_draft(script_id)
        if draft["status"] != "draft":
            raise ValueError("script is already published")
        script = Script.model_validate(draft["ir"])
        profile_for(script)
        report = lint_script(script)
        if not report.passed:
            raise ValueError("linter blockers must be resolved")
        if any(not resolved for _, item, resolved in self.reviews(script_id)
               if item.conflict_type != "by_design"):
            raise ValueError("review items must be resolved")
        with self.events.connect() as db:
            db.execute("UPDATE scripts SET status='published' WHERE script_id=?", (script_id,))
            db.execute("INSERT INTO script_versions VALUES (?,?,?,CURRENT_TIMESTAMP)",
                       (script_id, script.ir_version, json.dumps(draft["ir"], ensure_ascii=False)))
        return script

    def load_published(self, script_id: str) -> Script:
        draft = self.get_draft(script_id)
        if draft["status"] != "published":
            raise ValueError("script is not published")
        return Script.model_validate(draft["ir"])
