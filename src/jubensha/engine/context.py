import json

from jubensha.engine.perception import PerceptionView
from jubensha.engine.claims import ClaimJournal
from jubensha.schema.events import GameEvent, EventType


def build_context(p: PerceptionView, topic: str,
                  events: list[GameEvent]) -> list[dict[str, str]]:
    role_id = p.role_id
    words = set(topic)
    knowledge = p.known_events + p.known_clues
    relevant = sorted(knowledge, key=lambda x: sum(ch in json.dumps(x, ensure_ascii=False) for ch in words), reverse=True)[:8]
    visible = [e for e in events if "*" in e.visible_to or role_id in e.visible_to]
    speech = [e for e in visible if e.type in (EventType.PLAYER_INPUT, EventType.NPC_SPEECH, EventType.DM_NARRATION)]
    layers = [
        ("L1 身份卡", {"name": p.display_name, "profile": p.public_profile,
                     "goals": p.private_goals, "style": p.persona_style,
                     "constraints": p.speech_constraints, "forbidden_topics": p.forbidden_topics}),
        ("L2 知识切片", {"knowledge": relevant, "beliefs": p.false_beliefs}),
        ("L3 声明日志", ClaimJournal(events, role_id).recent()),
        ("L4 场景缓冲", [e.payload for e in speech[-8:]]),
        ("L5 公共摘要", p.public_summary),
        ("L6 关系笔记", p.relationships),
    ]
    messages = [{"role": "system", "content": f"{name}: {json.dumps(value, ensure_ascii=False)}"} for name, value in layers]
    messages.append({"role": "user", "content": topic[:500]})
    while sum(len(m["content"]) for m in messages) // 2 > 3000:
        for index in (3, 2, 1):
            if len(messages[index]["content"]) > 100:
                messages[index]["content"] = messages[index]["content"][:len(messages[index]["content"]) // 2]
                break
        else:
            break
    return messages
