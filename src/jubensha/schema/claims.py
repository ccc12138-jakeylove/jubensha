from typing import Literal

from pydantic import BaseModel, ConfigDict


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str
    role_id: str
    turn: int
    proposition: str
    truth_value: Literal["true", "false", "unknown"]
    is_lie: bool
    evidence_ids: list[str]
