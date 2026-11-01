from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from jubensha.engine.fsm import Phase


class Note(BaseModel):
    text: str
    turn: int


class SeatState(BaseModel):
    seat_id: str
    role_id: str | None = None
    private_clue_ids: list[str] = Field(default_factory=list)
    notebook: list[Note] = Field(default_factory=list)
    search_points: int = 0
    claims_made: list[str] = Field(default_factory=list)


class GameState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    game_id: str
    script_id: str
    act_id: str
    phase: Phase = Phase.ENTRY
    turn: int = 0
    seats: dict[str, SeatState]
    public_clue_ids: list[str] = Field(default_factory=list)
    vote_role_id: str | None = None
    vote_motive: str = ""
    vote_evidence_ids: list[str] = Field(default_factory=list)


class GraphState(BaseModel):
    game_id: str
    phase: Phase
    act_id: str
    turn: int
    last_player_input: str = ""
    intent: str = ""
    target_role_ids: list[str] = Field(default_factory=list)
    pending_tool_calls: list[dict] = Field(default_factory=list)
    perception_view: dict[str, dict] = Field(default_factory=dict)
    public_view: dict = Field(default_factory=dict)
    director_flags: dict = Field(default_factory=dict)
