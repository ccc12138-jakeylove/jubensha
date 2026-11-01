import re

from jubensha.schema.events import EventType, GameEvent


def normalize_probe(text: str) -> str:
    return "".join(re.findall(r"[\w\u4e00-\u9fff]+", text.lower()))


class ClaimJournal:
    def __init__(self, events: list[GameEvent], role_id: str):
        self.events = events
        self.role_id = role_id

    def recent(self, limit: int = 10) -> list[str]:
        return [event.payload["proposition"] for event in self.events
                if event.type == EventType.CLAIM
                and event.payload.get("role_id") == self.role_id
                and ("*" in event.visible_to or self.role_id in event.visible_to)][-limit:]

    def prior_answer(self, question: str) -> tuple[str, bool, list[str]] | None:
        probe = normalize_probe(question)
        if not probe:
            return None
        for event in reversed(self.events):
            if event.type == EventType.PHASE_CHANGE and "act_id" in event.payload:
                break
            if "*" not in event.visible_to and self.role_id not in event.visible_to:
                continue
            if event.type == EventType.CLAIM and event.payload.get("role_id") == self.role_id:
                if event.payload.get("probe") == probe:
                    return (event.payload["proposition"], event.payload["is_lie"],
                            event.payload.get("evidence_ids", []))
        return None
