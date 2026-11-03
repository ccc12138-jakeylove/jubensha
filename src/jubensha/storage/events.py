import os
from pathlib import Path
from uuid import uuid4

from jubensha.schema.events import GameEvent
from jubensha.schema.state import GameState, SeatState
from jubensha.engine.fsm import Phase
from jubensha.storage import db as pg


class EventStore:
    """对局事件与轨迹的 PostgreSQL 存储。

    `path` 既可以是连接串（推荐），也可以忽略；非连接串一律回落到
    `PG_DSN` / `GAME_DB` / 默认本地库，便于沿用旧的调用写法。
    """

    schema_override: str | None = None

    def __init__(self, path: str | Path | None = None, *, schema: str | None = None):
        self.dsn = pg.resolve_dsn(path)
        self.schema = schema or type(self).schema_override or os.getenv("PG_SCHEMA") or None
        self.path = self.dsn
        with self.connect() as connection:
            pg.ensure_schema(connection, self.dsn, self.schema)

    def connect(self):
        return pg.connect(self.dsn, self.schema)

    def create_game(self, game_id: str, script_id: str, act_id: str,
                    seat_id: str = "seat_1", *, is_preview: bool = False) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO games (game_id,script_id,act_id,seat_id,is_preview) VALUES (%s,%s,%s,%s,%s)",
                (game_id, script_id, act_id, seat_id, int(is_preview)))
            connection.execute("INSERT INTO game_seats VALUES (%s,%s,NULL)", (game_id, seat_id))

    def create_game_idempotent(self, script_id: str, act_id: str, key: str,
                               seat_id: str = "seat_1") -> str:
        with self.connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"create:{key}",))
            existing = connection.execute(
                "SELECT script_id,game_id FROM game_create_keys WHERE idempotency_key=%s",
                (key,)).fetchone()
            if existing:
                if existing["script_id"] != script_id:
                    raise ValueError("idempotency key was used for a different script")
                return existing["game_id"]
            game_id = uuid4().hex
            connection.execute("INSERT INTO games (game_id,script_id,act_id,seat_id) VALUES (%s,%s,%s,%s)",
                               (game_id, script_id, act_id, seat_id))
            connection.execute("INSERT INTO game_seats VALUES (%s,%s,NULL)", (game_id, seat_id))
            connection.execute("INSERT INTO game_create_keys VALUES (%s,%s,%s)", (key, script_id, game_id))
            return game_id

    def add_seat(self, game_id: str, seat_id: str, role_id: str | None = None) -> None:
        with self.connect() as connection:
            if not connection.execute("SELECT 1 FROM games WHERE game_id=%s", (game_id,)).fetchone():
                raise KeyError(game_id)
            connection.execute("INSERT INTO game_seats VALUES (%s,%s,%s)", (game_id, seat_id, role_id))

    def append(self, event: GameEvent) -> GameEvent:
        with self.connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"seq:{event.game_id}",))
            next_seq = connection.execute(
                "SELECT COALESCE(MAX(seq),0)+1 FROM game_events WHERE game_id=%s",
                (event.game_id,)).fetchone()[0]
            saved = event.model_copy(update={"seq": next_seq})
            connection.execute("INSERT INTO game_events VALUES (%s,%s,%s)",
                               (saved.game_id, saved.seq, saved.model_dump_json()))
        return saved

    def events(self, game_id: str, up_to_seq: int | None = None) -> list[GameEvent]:
        with self.connect() as connection:
            if up_to_seq is None:
                rows = connection.execute(
                    "SELECT event_json FROM game_events WHERE game_id=%s ORDER BY seq", (game_id,))
            else:
                rows = connection.execute(
                    "SELECT event_json FROM game_events WHERE game_id=%s AND seq<=%s ORDER BY seq",
                    (game_id, up_to_seq))
            return [GameEvent.model_validate_json(row[0]) for row in rows]

    def events_for_seat(self, game_id: str, seat_id: str,
                        up_to_seq: int | None = None) -> list[GameEvent]:
        with self.connect() as connection:
            seat = connection.execute(
                "SELECT role_id FROM game_seats WHERE game_id=%s AND seat_id=%s",
                (game_id, seat_id)).fetchone()
            if seat is None:
                raise PermissionError("seat does not belong to this game")
        principals = {seat_id}
        if seat["role_id"]:
            principals.add(seat["role_id"])
        return [event for event in self.events(game_id, up_to_seq)
                if "*" in event.visible_to or principals.intersection(event.visible_to)]

    def latest_game(self) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT game_id FROM games ORDER BY created_at DESC, game_id DESC LIMIT 1").fetchone()
            return row[0] if row else None

    def game_script_id(self, game_id: str) -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT script_id FROM games WHERE game_id=%s",
                                     (game_id,)).fetchone()
            if row is None:
                raise KeyError(game_id)
            return row[0]

    def is_preview_game(self, game_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute("SELECT is_preview FROM games WHERE game_id=%s",
                                     (game_id,)).fetchone()
        if row is None:
            raise KeyError(game_id)
        return bool(row[0])

    def load(self, game_id: str, search_budget: int, private_budget: int = 2,
             up_to_seq: int | None = None) -> GameState:
        with self.connect() as connection:
            game = connection.execute("SELECT * FROM games WHERE game_id=%s", (game_id,)).fetchone()
        if game is None:
            raise KeyError(game_id)
        with self.connect() as connection:
            seat_rows = connection.execute(
                "SELECT seat_id,role_id FROM game_seats WHERE game_id=%s ORDER BY seat_id",
                (game_id,)).fetchall()
        seats = {row["seat_id"]: SeatState(seat_id=row["seat_id"], role_id=row["role_id"],
                                           search_points=search_budget) for row in seat_rows}
        if not seats:
            seats[game["seat_id"]] = SeatState(seat_id=game["seat_id"], search_points=search_budget)
        state = GameState(game_id=game_id, script_id=game["script_id"], act_id=game["act_id"], seats=seats)
        for event in self.events(game_id, up_to_seq=up_to_seq):
            state.turn = max(state.turn, event.turn)
            if event.type.value == "phase_change":
                state.phase = Phase(event.payload["to"])
                if state.phase == Phase.PRIVATE:
                    state.private_chats_used += 1
                    state.private_role_id = event.payload["role_id"]
                elif event.phase == Phase.PRIVATE:
                    state.private_role_id = None
                if "act_id" in event.payload:
                    state.act_id = event.payload["act_id"]
                    for seat in seats.values():
                        seat.search_points = event.payload.get("search_points_budget", search_budget)
                    state.search_counts.clear()
                    state.private_chats_used = 0
            elif event.type.value == "clue_found":
                clue_id = event.payload["clue_id"]
                actor_seat = seats.get(event.actor_seat_id) or next(iter(seats.values()))
                actor_seat.search_points -= event.payload.get("search_cost", 0)
                location_id = event.payload["location_id"]
                state.search_counts[location_id] = state.search_counts.get(location_id, 0) + 1
                if event.visible_to == ["*"]:
                    state.public_clue_ids.append(clue_id)
                else:
                    for seat_id in event.visible_to:
                        if seat_id in seats:
                            seats[seat_id].private_clue_ids.append(clue_id)
            elif event.type.value == "vote":
                state.vote_role_id = event.payload["role_id"]
                state.vote_motive = event.payload["motive"]
                state.vote_evidence_ids = event.payload["evidence_ids"]
                if event.actor_seat_id in seats:
                    seats[event.actor_seat_id].claims_made.append(event.payload["motive"])
        return state

    def load_for_seat(self, game_id: str, seat_id: str, search_budget: int,
                      up_to_seq: int | None = None) -> GameState:
        state = self.load(game_id, search_budget, up_to_seq=up_to_seq)
        if seat_id not in state.seats:
            raise PermissionError("seat does not belong to this game")
        own_votes = [event for event in self.events_for_seat(game_id, seat_id, up_to_seq)
                     if event.type.value == "vote" and event.actor_seat_id == seat_id]
        latest = own_votes[-1].payload if own_votes else {}
        return state.model_copy(update={
            "seats": {seat_id: state.seats[seat_id]},
            "vote_role_id": latest.get("role_id"),
            "vote_motive": latest.get("motive", ""),
            "vote_evidence_ids": latest.get("evidence_ids", []),
        })

    def trace(self, game_id: str, node: str, prompt_version: str, input_tokens: int,
              output_tokens: int, latency_ms: int, cost_usd: float | None = None,
              model: str | None = None, prompt_hash: str | None = None,
              route_reason: str | None = None, cache_hit: bool = False) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO llm_traces (game_id,node,prompt_version,input_tokens,output_tokens,"
                "latency_ms,cost_usd,model,prompt_hash,route_reason,cache_hit) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (game_id, node, prompt_version, input_tokens, output_tokens, latency_ms,
                 cost_usd, model, prompt_hash, route_reason, int(cache_hit)))

    def guard_case(self, game_id: str, role_id: str, question: str,
                   candidate: str, reason: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO guard_cases (game_id,role_id,question,candidate,reason) VALUES (%s,%s,%s,%s,%s)",
                (game_id, role_id, question, candidate, reason))

    def guard_cases(self, game_id: str) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM guard_cases WHERE game_id=%s ORDER BY id", (game_id,))]

    def cache_get(self, key: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute("SELECT response_text FROM llm_cache WHERE cache_key=%s",
                                     (key,)).fetchone()
        return row[0] if row else None

    def cache_put(self, key: str, response: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO llm_cache (cache_key,response_text) VALUES (%s,%s) "
                "ON CONFLICT (cache_key) DO UPDATE SET response_text=EXCLUDED.response_text",
                (key, response))

    def trace_summary(self, script_id: str | None = None) -> list[dict]:
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT t.node,t.model,t.input_tokens,t.output_tokens,t.latency_ms,t.cost_usd,"
                "t.cache_hit FROM llm_traces t LEFT JOIN games g ON g.game_id=t.game_id "
                "WHERE %s::text IS NULL OR g.script_id=%s::text",
                (script_id, script_id))]
        groups: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            groups.setdefault((row["model"] or "unknown", row["node"]), []).append(row)
        summary = []
        for (model, node), items in sorted(groups.items()):
            latencies = sorted(item["latency_ms"] for item in items if not item["cache_hit"])
            summary.append({"model": model, "node": node, "calls": len(items),
                            "cache_hits": sum(item["cache_hit"] or 0 for item in items),
                            "input_tokens": sum(item["input_tokens"] for item in items),
                            "output_tokens": sum(item["output_tokens"] for item in items),
                            "cost_usd": sum(item["cost_usd"] or 0 for item in items),
                            "p50_ms": latencies[len(latencies) // 2] if latencies else None,
                            "p95_ms": latencies[int(.95 * (len(latencies) - 1))] if latencies else None})
        return summary
