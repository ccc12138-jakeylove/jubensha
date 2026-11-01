from pydantic import BaseModel, ConfigDict

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
    false_beliefs: list[dict]
    forbidden_topics: list[str]
    public_summary: dict
    relationships: list[dict]


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
                     if r.is_public or (r.from_role == role_id or r.to_role == role_id)]
    return PerceptionView(
        role_id=role_id, display_name=character.display_name,
        public_profile=character.public_profile, private_goals=list(character.private_goals),
        persona_style=character.persona_style, speech_constraints=list(character.speech_constraints),
        known_events=events, known_clues=clues,
        false_beliefs=[b.model_dump(exclude={"refuted_by_clue_ids"}) for b in knowledge.false_beliefs],
        forbidden_topics=list(knowledge.forbidden_topics), public_summary=public,
        relationships=relationships,
    )
