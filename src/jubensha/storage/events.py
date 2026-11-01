import json
import sqlite3
from pathlib import Path

from jubensha.schema.events import GameEvent
from jubensha.schema.state import GameState, SeatState
from jubensha.engine.fsm import Phase


class EventStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS games (
                    game_id TEXT PRIMARY KEY, script_id TEXT NOT NULL, act_id TEXT NOT NULL,
                    seat_id TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS game_events (
                    game_id TEXT NOT NULL, seq INTEGER NOT NULL, event_json TEXT NOT NULL,
                    PRIMARY KEY (game_id, seq)
                );
                CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON game_events
                BEGIN SELECT RAISE(ABORT, 'game_events is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON game_events
                BEGIN SELECT RAISE(ABORT, 'game_events is append-only'); END;
                CREATE TABLE IF NOT EXISTS llm_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT NOT NULL,
                    node TEXT NOT NULL, prompt_version TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
                    latency_ms INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def create_game(self, game_id: str, script_id: str, act_id: str, seat_id: str = "seat_1") -> None:
        with self.connect() as db:
            db.execute("INSERT INTO games (game_id,script_id,act_id,seat_id) VALUES (?,?,?,?)",
                       (game_id, script_id, act_id, seat_id))

    def append(self, event: GameEvent) -> GameEvent:
        with self.connect() as db:
            next_seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM game_events WHERE game_id=?",
                                  (event.game_id,)).fetchone()[0]
            saved = event.model_copy(update={"seq": next_seq})
            db.execute("INSERT INTO game_events VALUES (?,?,?)",
                       (saved.game_id, saved.seq, saved.model_dump_json()))
        return saved

    def events(self, game_id: str) -> list[GameEvent]:
        with self.connect() as db:
            rows = db.execute("SELECT event_json FROM game_events WHERE game_id=? ORDER BY seq", (game_id,))
            return [GameEvent.model_validate_json(row[0]) for row in rows]

    def latest_game(self) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT game_id FROM games ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
            return row[0] if row else None

    def load(self, game_id: str, search_budget: int) -> GameState:
        with self.connect() as db:
            game = db.execute("SELECT * FROM games WHERE game_id=?", (game_id,)).fetchone()
        if game is None:
            raise KeyError(game_id)
        seat = SeatState(seat_id=game["seat_id"], search_points=search_budget)
        state = GameState(game_id=game_id, script_id=game["script_id"], act_id=game["act_id"], seats={seat.seat_id: seat})
        for event in self.events(game_id):
            state.turn = max(state.turn, event.turn)
            if event.type.value == "phase_change":
                state.phase = Phase(event.payload["to"])
                if "act_id" in event.payload:
                    state.act_id = event.payload["act_id"]
            elif event.type.value == "clue_found":
                clue_id = event.payload["clue_id"]
                if event.visible_to == ["*"]:
                    state.public_clue_ids.append(clue_id)
                else:
                    seat.private_clue_ids.append(clue_id)
            elif event.type.value == "vote":
                state.vote_role_id = event.payload["role_id"]
                state.vote_motive = event.payload["motive"]
                state.vote_evidence_ids = event.payload["evidence_ids"]
                seat.claims_made.append(event.payload["motive"])
        return state

    def trace(self, game_id: str, node: str, prompt_version: str, input_tokens: int,
              output_tokens: int, latency_ms: int) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO llm_traces (game_id,node,prompt_version,input_tokens,output_tokens,latency_ms) VALUES (?,?,?,?,?,?)",
                       (game_id, node, prompt_version, input_tokens, output_tokens, latency_ms))
