import os
from collections.abc import Iterator, Sequence
from typing import Any

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    CheckpointTuple,
    WRITES_IDX_MAP,
    get_checkpoint_id,
    get_checkpoint_metadata,
)

from jubensha.storage import db as pg


class PgCheckpointer(BaseCheckpointSaver):
    def __init__(self, path: str | None = None, *, schema: str | None = None):
        super().__init__()
        self.dsn = pg.resolve_dsn(path)
        self.schema = schema or os.getenv("PG_SCHEMA") or None
        self.path = self.dsn
        with self.connect() as connection:
            pg.ensure_schema(connection, self.dsn, self.schema)

    def connect(self):
        return pg.connect(self.dsn, self.schema)

    def get_tuple(self, config):
        configurable = config["configurable"]
        thread_id = configurable["thread_id"]
        namespace = configurable.get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)
        with self.connect() as db:
            if checkpoint_id:
                row = db.execute(
                    "SELECT * FROM graph_checkpoints WHERE thread_id=%s AND namespace=%s "
                    "AND checkpoint_id=%s",
                    (thread_id, namespace, checkpoint_id)).fetchone()
            else:
                row = db.execute(
                    "SELECT * FROM graph_checkpoints WHERE thread_id=%s AND namespace=%s "
                    "ORDER BY checkpoint_id DESC LIMIT 1",
                    (thread_id, namespace)).fetchone()
            if row is None:
                return None
            writes = db.execute(
                "SELECT * FROM graph_writes WHERE thread_id=%s AND namespace=%s AND checkpoint_id=%s "
                "ORDER BY write_index, task_id",
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
                "SELECT checkpoint_id FROM graph_checkpoints WHERE thread_id=%s AND namespace=%s "
                "ORDER BY checkpoint_id DESC",
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
            db.execute(
                "INSERT INTO graph_checkpoints VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (thread_id,namespace,checkpoint_id) DO UPDATE SET "
                "parent_id=EXCLUDED.parent_id,checkpoint_type=EXCLUDED.checkpoint_type,"
                "checkpoint_blob=EXCLUDED.checkpoint_blob,metadata_type=EXCLUDED.metadata_type,"
                "metadata_blob=EXCLUDED.metadata_blob",
                (thread_id, namespace, checkpoint["id"], configurable.get("checkpoint_id"),
                 checkpoint_type, checkpoint_blob, metadata_type, metadata_blob))
        return {"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace,
                                 "checkpoint_id": checkpoint["id"]}}

    def put_writes(self, config, writes: Sequence[tuple[str, Any]], task_id: str, task_path: str = ""):
        configurable = config["configurable"]
        with self.connect() as db:
            for index, (channel, value) in enumerate(writes):
                value_type, value_blob = self.serde.dumps_typed(value)
                db.execute(
                    "INSERT INTO graph_writes VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING",
                    (configurable["thread_id"], configurable.get("checkpoint_ns", ""),
                     configurable["checkpoint_id"], task_id, WRITES_IDX_MAP.get(channel, index),
                     channel, value_type, value_blob))

    def delete_thread(self, thread_id: str):
        with self.connect() as db:
            db.execute("DELETE FROM graph_writes WHERE thread_id=%s", (thread_id,))
            db.execute("DELETE FROM graph_checkpoints WHERE thread_id=%s", (thread_id,))
