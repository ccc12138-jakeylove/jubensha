from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from jubensha.engine.fsm import Phase


class EventType(str, Enum):
    PLAYER_INPUT = "player_input"
    NPC_SPEECH = "npc_speech"
    DM_NARRATION = "dm_narration"
    CLUE_FOUND = "clue_found"
    PHASE_CHANGE = "phase_change"
    CLAIM = "claim"
    VOTE = "vote"

    @classmethod
    def _missing_(cls, value):
        if not isinstance(value, str) or not value:
            return None
        member = str.__new__(cls, value)
        member._name_ = f"EXTENSION_{value.upper()}"
        member._value_ = value
        return member


class GameEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seq: int
    game_id: str
    actor_seat_id: str
    turn: int
    phase: Phase
    type: EventType
    payload: dict
    visible_to: list[str]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
