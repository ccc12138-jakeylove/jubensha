from pydantic import BaseModel, ConfigDict, Field

from jubensha.schema.ir import WinCondition


class RubricItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    weight: float = Field(gt=0)
    description: str


class GenreProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    genre: str
    win_condition: WinCondition
    dm_tone: str
    rubric: list[RubricItem]
    parser_expectations: list[str]
