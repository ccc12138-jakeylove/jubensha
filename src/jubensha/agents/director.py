from pydantic import BaseModel, ConfigDict

from jubensha.engine.fsm import Phase
from jubensha.schema.events import EventType, GameEvent


class DirectorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    reason: str
    target: str | None = None
    level: int = 0
    trigger_clue_id: str | None = None


def decide(phase: Phase, events: list[GameEvent], public_profiles: dict[str, str],
           topic: str = "", exclude_roles: set[str] | None = None,
           discovered_clues: dict[str, str] | None = None) -> DirectorDecision:
    if phase != Phase.ACT_OPEN:
        return DirectorDecision(action="none", reason="not public discussion")
    public = [event for event in events if "*" in event.visible_to]
    act_start = max((event.seq for event in public if event.type == EventType.PHASE_CHANGE
                     and event.payload.get("to") == Phase.READ.value), default=0)
    current = [event for event in public if event.seq > act_start]
    proactive = [event for event in current if event.type == EventType.NPC_SPEECH
                 and event.payload.get("proactive")]
    seen_claims = set()
    progress_turns = []
    for event in current:
        if event.type in (EventType.CLUE_FOUND, EventType.PHASE_CHANGE):
            progress_turns.append(event.turn)
        elif event.type == EventType.CLAIM:
            claim = event.payload.get("proposition", "").strip()
            if claim and claim not in seen_claims:
                seen_claims.add(claim)
                progress_turns.append(event.turn)
    last_progress_turn = max(progress_turns, default=0)
    last_turn = max((event.turn for event in current), default=0)
    idle_turns = max(0, last_turn - last_progress_turn)
    asked = [event.payload.get("role_id") for event in current
             if event.type == EventType.PLAYER_INPUT and event.payload.get("role_id")]
    candidates = [role_id for role_id in public_profiles
                  if role_id not in {event.payload.get("role_id") for event in proactive}
                  and role_id not in (exclude_roles or set())]
    if idle_turns >= 16:
        return DirectorDecision(action="hint", reason="prolonged stall", level=3)
    if idle_turns >= 12:
        return DirectorDecision(action="hint", reason="stalled discussion", level=2)
    if idle_turns >= 8:
        return DirectorDecision(action="proactive" if candidates else "hint",
                                reason="no progress for eight turns",
                                target=candidates[0] if candidates else None, level=1)
    reacted_clues = {event.payload.get("trigger_clue_id") for event in proactive}
    fresh = [event.payload["clue_id"] for event in current
             if event.type == EventType.CLUE_FOUND
             and event.payload.get("clue_id") in (discovered_clues or {})
             and event.payload.get("clue_id") not in reacted_clues]
    if fresh:
        clue_id = fresh[-1]
        available = [role_id for role_id in public_profiles if role_id not in (exclude_roles or set())]
        if available:
            clue_chars = set(discovered_clues[clue_id])
            available.sort(key=lambda role_id: sum(char in public_profiles[role_id]
                                                    for char in clue_chars), reverse=True)
            return DirectorDecision(action="proactive", reason="react to public clue",
                                    target=available[0], trigger_clue_id=clue_id)
    if len(proactive) < 2 and candidates and (last_turn >= 1 or len(asked) >= 1):
        topic_chars = set(topic)
        candidates.sort(key=lambda role_id: (sum(char in public_profiles[role_id] for char in topic_chars),
                                             -asked[-3:].count(role_id)), reverse=True)
        return DirectorDecision(action="proactive", reason="offer another public perspective",
                                target=candidates[0])
    return DirectorDecision(action="none", reason="discussion progressing")
