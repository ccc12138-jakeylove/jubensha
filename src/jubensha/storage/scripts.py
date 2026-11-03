import json
from pydantic import ValidationError
from hashlib import sha256
from uuid import uuid4

from jubensha.compiler.lint import lint_script
from jubensha.compiler.content import fingerprint_match, simhash
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
                CREATE TABLE IF NOT EXISTS content_fingerprints (
                    script_id TEXT PRIMARY KEY, algorithm TEXT NOT NULL,
                    hash TEXT NOT NULL, source TEXT NOT NULL,
                    matched_script_id TEXT
                );
                CREATE TABLE IF NOT EXISTS script_revisions (
                    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    script_id TEXT NOT NULL, ir_json TEXT NOT NULL,
                    diff_summary TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor TEXT NOT NULL, action TEXT NOT NULL,
                    target TEXT NOT NULL, detail TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            for table, additions in {
                "scripts": {
                    "ir_version": "TEXT", "content_hash": "TEXT", "difficulty": "INTEGER",
                    "content_rating": "TEXT", "published_at": "TEXT", "archived_at": "TEXT",
                    "source_upload_id": "TEXT",
                },
                "script_uploads": {
                    "authorized_at": "TEXT", "rights_source": "TEXT", "rights_contact": "TEXT",
                    "distribution_scope": "TEXT NOT NULL DEFAULT 'pending'",
                },
                "script_versions": {
                    "parent_version": "TEXT", "diff_summary": "TEXT", "created_by": "TEXT",
                },
            }.items():
                existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                for column, data_type in additions.items():
                    if column not in existing:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {data_type}")

    @staticmethod
    def content_hash(ir_json: str) -> str:
        return sha256(ir_json.encode("utf-8")).hexdigest()

    def register_fixture(self, script: Script) -> None:
        ir_json = script.model_dump_json()
        digest = self.content_hash(ir_json)
        with self.events.connect() as db:
            existing = db.execute("SELECT source_filename,ir_json FROM scripts WHERE script_id=?",
                                  (script.script_id,)).fetchone()
            if existing is not None and existing["source_filename"] != "builtin fixture":
                raise ValueError("fixture script_id conflicts with an imported script")
            if existing is None:
                db.execute("INSERT INTO scripts (script_id,title,status,source_filename,source_text,ir_json,ir_version,content_hash,difficulty,content_rating,published_at) VALUES (?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                           (script.script_id, script.title, "published", "builtin fixture", "",
                            ir_json, script.ir_version, digest, script.difficulty, script.content_rating))
            elif self.content_hash(existing["ir_json"]) != digest:
                db.execute("UPDATE scripts SET title=?,ir_json=?,ir_version=?,content_hash=?,difficulty=?,content_rating=? WHERE script_id=?",
                           (script.title, ir_json, script.ir_version, digest, script.difficulty,
                            script.content_rating, script.script_id))
            version = f"{script.ir_version}+{digest[:12]}"
            db.execute("INSERT OR IGNORE INTO script_versions (script_id,version,ir_json,created_by) VALUES (?,?,?,?)",
                       (script.script_id, version, ir_json, "fixture"))

    def save_upload(self, filename: str, content: bytes,
                    rights_source: str = "author confirmed", rights_contact: str = "",
                    rights_confirmed: bool = True,
                    distribution_scope: str | None = None) -> str:
        if not rights_source.strip():
            raise ValueError("rights source is required")
        if len(content) > 10_000_000:
            raise ValueError("document exceeds 10 MB")
        scope = distribution_scope or ("authorized" if rights_confirmed else "pending")
        if scope not in {"authorized", "pending", "local_only"} or (rights_confirmed and scope != "authorized"):
            raise ValueError("invalid distribution scope")
        upload_id = uuid4().hex
        with self.events.connect() as db:
            db.execute("INSERT INTO script_uploads (upload_id,filename,content,authorized_at,rights_source,rights_contact,distribution_scope) VALUES (?,?,?,CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,?,?,?)",
                       (upload_id, filename, content, int(rights_confirmed),
                        rights_source.strip(), rights_contact.strip(), scope))
        return upload_id

    def confirm_rights(self, upload_id: str, rights_source: str,
                       rights_contact: str = "") -> None:
        if not rights_source.strip():
            raise ValueError("rights source is required")
        with self.events.connect() as db:
            row = db.execute("SELECT distribution_scope FROM script_uploads WHERE upload_id=?", (upload_id,)).fetchone()
            if row is None:
                raise KeyError(upload_id)
            if row["distribution_scope"] == "local_only":
                raise ValueError("local-only material cannot be confirmed for publication")
            cursor = db.execute("UPDATE script_uploads SET authorized_at=CURRENT_TIMESTAMP,rights_source=?,rights_contact=?,distribution_scope='authorized' WHERE upload_id=?",
                                (rights_source.strip(), rights_contact.strip(), upload_id))
            if cursor.rowcount != 1:
                raise KeyError(upload_id)

    def restrict_to_local(self, script_id: str) -> None:
        with self.events.connect() as db:
            row = db.execute("SELECT source_upload_id FROM scripts WHERE script_id=? AND status='draft'",
                             (script_id,)).fetchone()
            if row is None or not row["source_upload_id"]:
                raise ValueError("uploaded draft required")
            db.execute("UPDATE script_uploads SET distribution_scope='local_only',authorized_at=NULL,rights_source='local verification only' WHERE upload_id=?",
                       (row["source_upload_id"],))
            db.execute("INSERT INTO audit_log (actor,action,target,detail) VALUES ('local','restrict_to_local',?,'user specified local validation only')",
                       (script_id,))

    def authorize_draft(self, script_id: str, rights_source: str) -> None:
        if not rights_source.strip():
            raise ValueError("rights source is required")
        with self.events.connect() as db:
            row = db.execute("SELECT source_upload_id FROM scripts WHERE script_id=? AND status='draft'",
                             (script_id,)).fetchone()
            if row is None or not row["source_upload_id"]:
                raise ValueError("uploaded draft required")
            db.execute("UPDATE script_uploads SET distribution_scope='authorized',authorized_at=CURRENT_TIMESTAMP,rights_source=? WHERE upload_id=?",
                       (rights_source.strip(), row["source_upload_id"]))
            db.execute("INSERT INTO audit_log (actor,action,target,detail) VALUES ('author','authorize_draft',?,?)",
                       (script_id, rights_source.strip()))

    def get_upload(self, upload_id: str) -> tuple[str, bytes]:
        with self.events.connect() as db:
            row = db.execute("SELECT filename,content FROM script_uploads WHERE upload_id=?",
                             (upload_id,)).fetchone()
        if row is None:
            raise KeyError(upload_id)
        return row["filename"], row["content"]

    def save_draft(self, draft: CompilationDraft, upload_id: str | None = None) -> str:
        script_id = str(draft.ir.get("script_id") or f"draft_{uuid4().hex}")
        draft.ir["script_id"] = script_id
        title = str(draft.ir.get("title") or draft.filename)
        with self.events.connect() as db:
            if db.execute("SELECT 1 FROM scripts WHERE script_id=?", (script_id,)).fetchone():
                raise ValueError("script_id already exists; edit the existing draft")
            ir_json = json.dumps(draft.ir, ensure_ascii=False)
            db.execute("INSERT INTO scripts (script_id,title,status,source_filename,source_text,ir_json,ir_version,content_hash,difficulty,content_rating,source_upload_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (script_id, title, "draft", draft.filename, draft.source_text,
                        ir_json, draft.ir.get("ir_version", "1.1"), self.content_hash(ir_json),
                        draft.ir.get("difficulty"), draft.ir.get("content_rating"), upload_id))
            if len(draft.source_text) >= 200:
                digest = simhash(draft.source_text)
                matches = [row["script_id"] for row in db.execute("SELECT script_id,hash FROM content_fingerprints")
                           if fingerprint_match(digest, row["hash"])]
                db.execute("INSERT INTO content_fingerprints (script_id,algorithm,hash,source,matched_script_id) VALUES (?,'simhash64',?,?,?)",
                           (script_id, digest, draft.filename, matches[0] if matches else None))
                if matches:
                    draft.review_items.append(ReviewItem(field_path="source_text", confidence=1,
                                                         conflict_type="copyright_similarity",
                                                         message=f"与剧本 {matches[0]} 高度相似，需核对改编授权"))
            for item in draft.review_items:
                db.execute("INSERT INTO review_items (script_id,item_json,resolved) VALUES (?,?,?)",
                           (script_id, item.model_dump_json(), int(item.resolved)))
        return script_id

    def list_scripts(self, *, status: str | None = None, genre: str | None = None,
                     difficulty: int | None = None) -> list[dict]:
        with self.events.connect() as db:
            rows = [dict(row) for row in db.execute(
                "SELECT script_id,title,status,source_filename,created_at,ir_version,content_hash,difficulty,content_rating,archived_at,json_extract(ir_json,'$.genre') AS genre FROM scripts ORDER BY created_at DESC")]
        return [row for row in rows if (status is None or row["status"] == status)
                and (genre is None or row["genre"] == genre)
                and (difficulty is None or row["difficulty"] == difficulty)]

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
        if not isinstance(parsed, dict) or parsed.get("script_id") != script_id:
            raise ValueError("script_id cannot change during review")
        try:
            script = Script.model_validate(parsed)
        except ValidationError as exc:
            script = None
            schema_error = str(exc)[:2000]
            parsed.pop("linter_report", None)
        else:
            report = lint_script(script)
            parsed["linter_report"] = report.model_dump()
        with self.events.connect() as db:
            old = draft["ir"]
            changed = sorted(key for key in set(old) | set(parsed) if old.get(key) != parsed.get(key))
            db.execute("INSERT INTO script_revisions (script_id,ir_json,diff_summary) VALUES (?,?,?)",
                       (script_id, json.dumps(old, ensure_ascii=False), ", ".join(changed)))
            ir_json = json.dumps(parsed, ensure_ascii=False)
            db.execute("UPDATE scripts SET ir_json=?,title=?,ir_version=?,content_hash=?,difficulty=?,content_rating=? WHERE script_id=?",
                       (ir_json, str(parsed.get("title") or draft["title"]),
                        str(parsed.get("ir_version") or "1.1"), self.content_hash(ir_json),
                        script.difficulty if script else None,
                        script.content_rating if script else None, script_id))
            db.execute("DELETE FROM review_items WHERE script_id=? AND json_extract(item_json, '$.conflict_type') IN ('script_bug','linter_warning','schema_error')",
                       (script_id,))
            if script is None:
                item = ReviewItem(field_path="*", confidence=0,
                                  conflict_type="schema_error", message=schema_error)
                db.execute("INSERT INTO review_items (script_id,item_json,resolved) VALUES (?,?,0)",
                           (script_id, item.model_dump_json()))
            else:
                for issue in report.blockers + [item for item in report.warnings if item.severity == "high"]:
                    item = ReviewItem(field_path=issue.target_id, confidence=0 if issue.severity == "blocker" else 0.5,
                                      conflict_type="script_bug" if issue.severity == "blocker" else "linter_warning",
                                      message=issue.message)
                    db.execute("INSERT INTO review_items (script_id,item_json,resolved) VALUES (?,?,0)",
                               (script_id, item.model_dump_json()))

    def refresh_draft_source(self, script_id: str, source_text: str) -> None:
        with self.events.connect() as db:
            cursor = db.execute("UPDATE scripts SET source_text=? WHERE script_id=? AND status='draft'",
                                (source_text, script_id))
            if cursor.rowcount != 1:
                raise ValueError("draft required")

    def revisions(self, script_id: str) -> list[dict]:
        with self.events.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT revision_id,diff_summary,created_at FROM script_revisions WHERE script_id=? ORDER BY revision_id DESC",
                (script_id,))]

    def rollback(self, script_id: str, revision_id: int) -> None:
        with self.events.connect() as db:
            row = db.execute("SELECT ir_json FROM script_revisions WHERE script_id=? AND revision_id=?",
                             (script_id, revision_id)).fetchone()
        if row is None:
            raise KeyError(revision_id)
        self.update_ir(script_id, row["ir_json"])
        with self.events.connect() as db:
            db.execute("INSERT INTO audit_log (actor,action,target,detail) VALUES ('local','rollback',?,?)",
                       (script_id, str(revision_id)))

    def versions(self, script_id: str) -> list[dict]:
        with self.events.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT version,parent_version,diff_summary,created_by,created_at FROM script_versions WHERE script_id=? ORDER BY created_at DESC,rowid DESC",
                (script_id,))]

    def archive(self, script_id: str) -> None:
        with self.events.connect() as db:
            cursor = db.execute("UPDATE scripts SET status='archived',archived_at=CURRENT_TIMESTAMP WHERE script_id=? AND status='published' AND source_filename!='builtin fixture'",
                                (script_id,))
            if cursor.rowcount != 1:
                raise ValueError("only imported published scripts can be archived")
            db.execute("INSERT INTO audit_log (actor,action,target,detail) VALUES ('local','archive',?,'')",
                       (script_id,))

    def audit(self, actor: str, action: str, target: str, detail: str = "") -> None:
        with self.events.connect() as db:
            db.execute("INSERT INTO audit_log (actor,action,target,detail) VALUES (?,?,?,?)",
                       (actor, action, target, detail))

    def delete_draft(self, script_id: str) -> None:
        with self.events.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,source_upload_id FROM scripts WHERE script_id=?",
                             (script_id,)).fetchone()
            if row is None:
                raise KeyError(script_id)
            if row["status"] != "draft":
                raise ValueError("only drafts can be deleted")
            db.execute("DELETE FROM review_items WHERE script_id=?", (script_id,))
            db.execute("DELETE FROM script_revisions WHERE script_id=?", (script_id,))
            db.execute("DELETE FROM content_fingerprints WHERE script_id=?", (script_id,))
            db.execute("DELETE FROM scripts WHERE script_id=?", (script_id,))
            upload_id = row["source_upload_id"]
            if upload_id and not db.execute("SELECT 1 FROM scripts WHERE source_upload_id=?",
                                            (upload_id,)).fetchone():
                db.execute("DELETE FROM script_uploads WHERE upload_id=?", (upload_id,))
            db.execute("INSERT INTO audit_log (actor,action,target,detail) VALUES ('local','delete_draft',?,'')",
                       (script_id,))

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
        if draft["source_upload_id"]:
            with self.events.connect() as db:
                rights = db.execute("SELECT authorized_at,distribution_scope FROM script_uploads WHERE upload_id=?",
                                    (draft["source_upload_id"],)).fetchone()
            if rights is None or not rights["authorized_at"] or rights["distribution_scope"] != "authorized":
                raise ValueError("script usage rights are not confirmed")
        with self.events.connect() as db:
            db.execute("UPDATE scripts SET status='published',published_at=CURRENT_TIMESTAMP WHERE script_id=?", (script_id,))
            version = f"{script.ir_version}+{self.content_hash(json.dumps(draft['ir'], ensure_ascii=False))[:12]}"
            db.execute("INSERT OR IGNORE INTO script_versions (script_id,version,ir_json,created_by) VALUES (?,?,?,?)",
                       (script_id, version, json.dumps(draft["ir"], ensure_ascii=False), "review"))
            db.execute("INSERT INTO audit_log (actor,action,target,detail) VALUES ('local','publish',?,'')",
                       (script_id,))
        return script

    def load_published(self, script_id: str) -> Script:
        draft = self.get_draft(script_id)
        if draft["status"] != "published":
            raise ValueError("script is not published")
        return Script.model_validate(draft["ir"])

    def load_preview(self, script_id: str) -> Script:
        draft = self.get_draft(script_id)
        if draft["status"] != "draft" or not draft["source_upload_id"]:
            raise ValueError("uploaded draft required for preview")
        with self.events.connect() as db:
            rights = db.execute("SELECT authorized_at,distribution_scope FROM script_uploads WHERE upload_id=?",
                                (draft["source_upload_id"],)).fetchone()
        if rights is None or not rights["authorized_at"] or rights["distribution_scope"] != "authorized":
            raise ValueError("script usage rights are not confirmed")
        script = Script.model_validate(draft["ir"])
        if not lint_script(script).passed:
            raise ValueError("linter blockers must be resolved before preview")
        return script

    def load_playable(self, script_id: str) -> Script:
        draft = self.get_draft(script_id)
        if draft["status"] not in ("published", "archived"):
            raise ValueError("script is not playable")
        return Script.model_validate(draft["ir"])
