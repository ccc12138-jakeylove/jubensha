import sqlite3
from collections.abc import Iterator, Sequence
from typing import Any

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    CheckpointTuple,
    WRITES_IDX_MAP,
    get_checkpoint_id,
    get_checkpoint_metadata,
)


class SQLiteCheckpointer(BaseCheckpointSaver):
    def __init__(self, path: str):
        super().__init__()
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS graph_checkpoints (
                    thread_id TEXT NOT NULL, namespace TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL, parent_id TEXT,
                    checkpoint_type TEXT NOT NULL, checkpoint_blob BLOB NOT NULL,
                    metadata_type TEXT NOT NULL, metadata_blob BLOB NOT NULL,
                    PRIMARY KEY (thread_id, namespace, checkpoint_id)
                );
                CREATE TABLE IF NOT EXISTS graph_writes (
                    thread_id TEXT NOT NULL, namespace TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL,
                    write_index INTEGER NOT NULL, channel TEXT NOT NULL,
                    value_type TEXT NOT NULL, value_blob BLOB NOT NULL,
                    PRIMARY KEY (thread_id, namespace, checkpoint_id, task_id, write_index)
                );
            """)

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def get_tuple(self, config):
        configurable = config["configurable"]
        thread_id = configurable["thread_id"]
        namespace = configurable.get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)
        with self.connect() as db:
            if checkpoint_id:
                row = db.execute(
                    "SELECT * FROM graph_checkpoints WHERE thread_id=? AND namespace=? AND checkpoint_id=?",
                    (thread_id, namespace, checkpoint_id)).fetchone()
            else:
                row = db.execute(
                    "SELECT * FROM graph_checkpoints WHERE thread_id=? AND namespace=? ORDER BY checkpoint_id DESC LIMIT 1",
                    (thread_id, namespace)).fetchone()
            if row is None:
                return None
            writes = db.execute(
                "SELECT * FROM graph_writes WHERE thread_id=? AND namespace=? AND checkpoint_id=? ORDER BY write_index, task_id",
                (thread_id, namespace, row["checkpoint_id"])).fetchall()
        full_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace,
                                        "checkpoint_id": row["checkpoint_id"]}}
        parent = ({"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace,
                                     "checkpoint_id": row["parent_id"]}} if row["parent_id"] else None)
        return CheckpointTuple(
            config=full_config,
            checkpoint=self.serde.loads_typed((row["checkpoint_type"], row["checkpoint_blob"])),
            metadata=self.serde.loads_typed((row["metadata_type"], row["metadata_blob"])),
            parent_config=parent,
            pending_writes=[(w["task_id"], w["channel"],
                             self.serde.loads_typed((w["value_type"], w["value_blob"]))) for w in writes],
        )

    def list(self, config, *, filter=None, before=None, limit=None) -> Iterator[CheckpointTuple]:
        if config is None:
            return
        thread_id = config["configurable"]["thread_id"]
        namespace = config["configurable"].get("checkpoint_ns", "")
        with self.connect() as db:
            ids = [row[0] for row in db.execute(
                "SELECT checkpoint_id FROM graph_checkpoints WHERE thread_id=? AND namespace=? ORDER BY checkpoint_id DESC",
                (thread_id, namespace))]
        count = 0
        for checkpoint_id in ids:
            if before and checkpoint_id >= get_checkpoint_id(before):
                continue
            item = self.get_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace,
                                                    "checkpoint_id": checkpoint_id}})
            if filter and any(item.metadata.get(k) != v for k, v in filter.items()):
                continue
            yield item
            count += 1
            if limit is not None and count >= limit:
                break

    def put(self, config, checkpoint, metadata, new_versions):
        configurable = config["configurable"]
        thread_id = configurable["thread_id"]
        namespace = configurable.get("checkpoint_ns", "")
        checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint)
        metadata_type, metadata_blob = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO graph_checkpoints VALUES (?,?,?,?,?,?,?,?)",
                       (thread_id, namespace, checkpoint["id"], configurable.get("checkpoint_id"),
                        checkpoint_type, checkpoint_blob, metadata_type, metadata_blob))
        return {"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace,
                                 "checkpoint_id": checkpoint["id"]}}

    def put_writes(self, config, writes: Sequence[tuple[str, Any]], task_id: str, task_path: str = ""):
        configurable = config["configurable"]
        with self.connect() as db:
            for index, (channel, value) in enumerate(writes):
                value_type, value_blob = self.serde.dumps_typed(value)
                db.execute("INSERT OR IGNORE INTO graph_writes VALUES (?,?,?,?,?,?,?,?)",
                           (configurable["thread_id"], configurable.get("checkpoint_ns", ""),
                            configurable["checkpoint_id"], task_id, WRITES_IDX_MAP.get(channel, index),
                            channel, value_type, value_blob))

    def delete_thread(self, thread_id: str):
        with self.connect() as db:
            db.execute("DELETE FROM graph_writes WHERE thread_id=?", (thread_id,))
            db.execute("DELETE FROM graph_checkpoints WHERE thread_id=?", (thread_id,))
