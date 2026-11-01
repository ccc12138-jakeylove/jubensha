from typing import Protocol

from jubensha.engine.context import build_context, context_size
from jubensha.engine.perception import PerceptionView
from jubensha.schema.events import EventType, GameEvent
from jubensha.schema.memory import MemorySummary


class MemoryStore(Protocol):
    def get(self, game_id: str, perspective: str, end_seq: int) -> MemorySummary | None: ...
    def put(self, summary: MemorySummary) -> None: ...


def visible_events(events: list[GameEvent], perspective: str) -> list[GameEvent]:
    return [event for event in events
            if "*" in event.visible_to or (perspective != "public" and perspective in event.visible_to)]


def summarize(game_id: str, perspective: str, events: list[GameEvent], end_seq: int) -> MemorySummary:
    authorized = visible_events([event for event in events if event.seq <= end_seq], perspective)
    structural = [event for event in authorized if event.type in (EventType.CLUE_FOUND, EventType.PHASE_CHANGE)]
    private_dialogue = [event for event in authorized if event.visible_to != ["*"]
                        and event.type in (EventType.PLAYER_INPUT, EventType.NPC_SPEECH)]
    dialogue = [event for event in authorized if event.type in
                (EventType.PLAYER_INPUT, EventType.NPC_SPEECH, EventType.DM_NARRATION)][-5:]
    selected = sorted({event.seq: event for event in structural + private_dialogue + dialogue}.values(),
                      key=lambda event: event.seq)
    lines = []
    for event in selected:
        payload = event.payload
        text = payload.get("text") or payload.get("clue_id") or payload.get("to") or ""
        if event.type == EventType.NPC_SPEECH:
            speaker = "我说" if payload.get("role_id") == perspective else f"{payload.get('role_id', 'NPC')}说"
        elif event.type == EventType.PLAYER_INPUT:
            speaker = "玩家说"
        elif event.type == EventType.DM_NARRATION:
            speaker = "DM说"
        else:
            speaker = event.type.value
        lines.append(f"#{event.seq} {speaker}: {text[:120]}")
    return MemorySummary(game_id=game_id, perspective=perspective, start_seq=1,
                         end_seq=end_seq, event_seqs=[event.seq for event in selected],
                         text="\n".join(lines)[-1200:])


def summaries_for_context(store: MemoryStore, game_id: str, role_id: str,
                          events: list[GameEvent], perception: PerceptionView,
                          topic: str) -> tuple[MemorySummary | None, MemorySummary | None]:
    speech = [event for event in visible_events(events, role_id)
              if event.type in (EventType.PLAYER_INPUT, EventType.NPC_SPEECH, EventType.DM_NARRATION)]
    act_boundary = any(event.type == EventType.PHASE_CHANGE and "act_id" in event.payload
                       for event in events)
    full_tokens = context_size(build_context(perception, topic, events, mode="full"))
    if len(speech) <= 8 or (full_tokens < 2400 and not act_boundary):
        return None, None
    end_seq = speech[-9].seq
    result = []
    for perspective in ("public", role_id):
        summary = store.get(game_id, perspective, end_seq)
        if summary is None:
            summary = summarize(game_id, perspective, events, end_seq)
            store.put(summary)
        result.append(summary)
    return result[0], result[1]
