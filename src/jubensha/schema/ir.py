from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from jubensha.engine.fsm import Phase


class IRModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WinCondition(IRModel):
    type: Literal["accuse", "vote", "escape", "custom"]
    required: list[str]
    partial_credit: bool = True
    rubric_id: str | None = None


class Act(IRModel):
    act_id: str
    order: int
    title: str
    public_narrative: str
    allowed_phases: list[Phase]
    entry_condition: str | None = None
    search_points_budget: int
    private_chat_budget: int = 2


class Character(IRModel):
    role_id: str
    display_name: str
    is_culprit: bool = False
    is_player_seat: bool = False
    public_profile: str
    private_goals: list[str]
    persona_style: str
    secret_ids: list[str]
    speech_constraints: list[str]


class TruthEvent(IRModel):
    event_id: str
    act_id: str
    t_start: int
    t_end: int | None
    location_id: str
    actor_ids: list[str]
    action: str
    observable: list[str]
    hidden: list[str]
    evidence_clue_ids: list[str]


class Clue(IRModel):
    clue_id: str
    display_name: str
    surface_text: str
    truth_value: Literal["true", "false", "misleading"]
    location_id: str
    act_available: list[str]
    search_cost: int = 1
    prerequisites: list[str] = []
    reveals_event_ids: list[str]
    reveals_secret_ids: list[str]
    visibility: Literal["public", "private"]
    red_herring: bool = False


class Location(IRModel):
    location_id: str
    display_name: str
    description: str
    searchable: bool = True
    capacity_per_act: int = 1
    act_availability: list[str]
    connected_to: list[str]


class LieTurn(IRModel):
    act: str
    probe: str
    answer: str


class Secret(IRModel):
    secret_id: str
    owner_role_id: str
    content: str
    exposed_by_clue_ids: list[str]
    leak_policy: Literal["deny", "deflect", "lie", "partial"]
    forbidden_claims: list[tuple[str, str, str]]
    lie_script: list[LieTurn] | None


class FalseBelief(IRModel):
    statement: str
    confidence: float
    source_event_id: str
    refuted_by_clue_ids: list[str]


class KnowledgeSlice(IRModel):
    role_id: str
    knows_event_ids: list[str]
    knows_clue_ids: list[str]
    false_beliefs: list[FalseBelief]
    forbidden_topics: list[str]


class Relationship(IRModel):
    from_role: str
    to_role: str
    type: Literal["lover", "kin", "debtor", "rival", "employer", "stranger"]
    is_public: bool
    evidence_clue_ids: list[str]


class LeakSurfaceSet(IRModel):
    secret_id: str
    fact: str
    paraphrases: list[str]
    implications: list[str]
    qa_probes: list[str]


class Provenance(IRModel):
    field_path: str
    source_doc: str
    source_span: tuple[int, int]
    confidence: float


class LintIssue(IRModel):
    code: str
    severity: Literal["blocker", "high", "medium"]
    target_id: str
    message: str
    suggestion: str | None


class SolvabilityResult(IRModel):
    solvable: bool
    optimal_path_clue_ids: list[str]
    missing_evidence: list[str]
    requires_human_review: bool = False


class LinterReport(IRModel):
    passed: bool
    blockers: list[LintIssue]
    warnings: list[LintIssue]
    solvability: SolvabilityResult


class Script(IRModel):
    script_id: str
    title: str
    genre: Literal["本格", "变格", "机制", "恐怖", "情感"]
    ir_version: str = "1.0"
    tone: str
    seat_range: tuple[int, int]
    win_condition: WinCondition
    acts: list[Act]
    characters: dict[str, Character]
    truth_events: list[TruthEvent]
    clues: dict[str, Clue]
    locations: dict[str, Location]
    secrets: dict[str, Secret]
    knowledge: dict[str, KnowledgeSlice]
    relationships: list[Relationship]
    leak_surfaces: dict[str, LeakSurfaceSet]
    provenance: dict[str, Provenance]
    linter_report: LinterReport | None = None
