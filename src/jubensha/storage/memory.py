from jubensha.schema.memory import MemorySummary
from jubensha.storage.events import EventStore


class SummaryStore:
    def __init__(self, events: EventStore):
        self.events = events

    def get(self, game_id: str, perspective: str, end_seq: int) -> MemorySummary | None:
        with self.events.connect() as db:
            row = db.execute(
                "SELECT summary_json FROM memory_summaries "
                "WHERE game_id=%s AND perspective=%s AND end_seq=%s",
                (game_id, perspective, end_seq)).fetchone()
        return MemorySummary.model_validate_json(row[0]) if row else None

    def put(self, summary: MemorySummary) -> None:
        with self.events.connect() as db:
            db.execute(
                "INSERT INTO memory_summaries VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (summary.game_id, summary.perspective, summary.end_seq, summary.model_dump_json()))
