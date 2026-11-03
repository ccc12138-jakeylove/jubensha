from pydantic import BaseModel, ConfigDict, Field

from jubensha.schema.ir import Script
from jubensha.schema.state import GameState
from jubensha.engine.world import PublicStore


class PerceptionView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_id: str
    display_name: str
    public_profile: str
    private_goals: list[str]
    persona_style: str
    speech_constraints: list[str]
    known_events: list[dict]
    known_clues: list[dict]
    known_statements: list[dict] = Field(default_factory=list)
    false_beliefs: list[dict]
    forbidden_topics: list[str]
    public_summary: dict
    relationships: list[dict]
    lie_cues: list[dict[str, str]]


def build_perception(script: Script, state: GameState, role_id: str) -> PerceptionView:
    character = script.characters[role_id]
    knowledge = script.knowledge[role_id]
    public = PublicStore(script).view(state)
    found = set(state.public_clue_ids)
    event_ids = set(knowledge.knows_event_ids)
    clue_ids = set(knowledge.knows_clue_ids) | found
    events = [{"event_id": e.event_id, "observable": e.observable}
              for e in script.truth_events if e.event_id in event_ids]
    clues = [{"clue_id": c.clue_id, "surface_text": c.surface_text}
             for c in script.clues.values() if c.clue_id in clue_ids]
    relationships = [r.model_dump(exclude={"evidence_clue_ids"}) for r in script.relationships
                     if r.is_public or ((r.from_role == role_id or r.to_role == role_id)
                                        and bool(r.evidence_clue_ids)
                                        and set(r.evidence_clue_ids).issubset(clue_ids))]
    lie_cues = [{"probe": turn.probe, "answer": turn.answer}
                for secret_id in character.secret_ids
                for turn in (script.secrets[secret_id].lie_script or [])
                if turn.act == state.act_id]
    current_order = next(act.order for act in script.acts if act.act_id == state.act_id)
    order_by_act = {act.act_id: act.order for act in script.acts}
    available_act_ids = {act.act_id for act in script.acts if act.order <= current_order}
    return PerceptionView(
        role_id=role_id, display_name=character.display_name,
        public_profile=character.public_profile,
        private_goals=character.goals_for_act(order_by_act, current_order),
        persona_style=character.persona_style, speech_constraints=list(character.speech_constraints),
        known_events=events, known_clues=clues,
        known_statements=[{"statement_id": item.statement_id, "text": item.text}
                          for item in knowledge.statements
                          if item.approved and (item.act_id is None or item.act_id in available_act_ids)],
        false_beliefs=[b.model_dump(exclude={"refuted_by_clue_ids"}) for b in knowledge.false_beliefs],
        forbidden_topics=list(knowledge.forbidden_topics), public_summary=public,
        relationships=relationships,
        lie_cues=lie_cues,
    )
