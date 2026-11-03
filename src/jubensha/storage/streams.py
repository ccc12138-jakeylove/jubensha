import json

from jubensha.storage.events import EventStore


class TurnStreams:
    def __init__(self, events: EventStore):
        self.events = events
        with events.connect() as db:
            db.execute("UPDATE turn_streams SET status='interrupted' WHERE status='running'")

    def begin(self, game_id: str, request_key: str, seat_id: str, request_hash: str) -> bool:
        with self.events.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"stream:{game_id}:{request_key}",))
            row = db.execute(
                "SELECT seat_id,request_hash FROM turn_streams WHERE game_id=%s AND request_key=%s",
                (game_id, request_key)).fetchone()
            if row:
                if (row["seat_id"], row["request_hash"]) != (seat_id, request_hash):
                    raise ValueError("idempotency key was used for a different turn")
                return False
            db.execute(
                "INSERT INTO turn_streams (game_id,request_key,seat_id,request_hash,status) "
                "VALUES (%s,%s,%s,%s,%s)",
                (game_id, request_key, seat_id, request_hash, "running"))
            return True

    def append(self, game_id: str, request_key: str, kind: str, payload: dict) -> int:
        with self.events.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"streamseq:{game_id}:{request_key}",))
            seq = db.execute(
                "SELECT COALESCE(MAX(seq),0)+1 FROM turn_stream_events WHERE game_id=%s AND request_key=%s",
                (game_id, request_key)).fetchone()[0]
            db.execute("INSERT INTO turn_stream_events VALUES (%s,%s,%s,%s,%s)",
                       (game_id, request_key, seq, kind, json.dumps(payload, ensure_ascii=False)))
            if kind in ("done", "error"):
                db.execute("UPDATE turn_streams SET status=%s WHERE game_id=%s AND request_key=%s",
                           ("completed" if kind == "done" else "failed", game_id, request_key))
            return seq

    def after(self, game_id: str, request_key: str, seq: int) -> list[dict]:
        with self.events.connect() as db:
            rows = db.execute(
                "SELECT seq,kind,payload_json FROM turn_stream_events "
                "WHERE game_id=%s AND request_key=%s AND seq>%s ORDER BY seq",
                (game_id, request_key, seq)).fetchall()
        return [{"seq": row["seq"], "kind": row["kind"],
                 "payload": json.loads(row["payload_json"])} for row in rows]

    def status(self, game_id: str, request_key: str) -> str:
        with self.events.connect() as db:
            row = db.execute("SELECT status FROM turn_streams WHERE game_id=%s AND request_key=%s",
                             (game_id, request_key)).fetchone()
        if row is None:
            raise KeyError(request_key)
        return row[0]
