from pydantic import BaseModel, ConfigDict


class MemorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    game_id: str
    perspective: str
    start_seq: int
    end_seq: int
    event_seqs: list[int]
    text: str
