from jubensha.schema.memory import MemorySummary
from jubensha.storage.events import EventStore


class SummaryStore:
    def __init__(self, events: EventStore):
        self.events = events
        with events.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS memory_summaries (
                    game_id TEXT NOT NULL, perspective TEXT NOT NULL,
                    end_seq INTEGER NOT NULL, summary_json TEXT NOT NULL,
                    PRIMARY KEY (game_id, perspective, end_seq)
                )
            """)

    def get(self, game_id: str, perspective: str, end_seq: int) -> MemorySummary | None:
        with self.events.connect() as db:
            row = db.execute("SELECT summary_json FROM memory_summaries WHERE game_id=? AND perspective=? AND end_seq=?",
                             (game_id, perspective, end_seq)).fetchone()
        return MemorySummary.model_validate_json(row[0]) if row else None

    def put(self, summary: MemorySummary) -> None:
        with self.events.connect() as db:
            db.execute("INSERT OR IGNORE INTO memory_summaries VALUES (?,?,?,?)",
                       (summary.game_id, summary.perspective, summary.end_seq, summary.model_dump_json()))
