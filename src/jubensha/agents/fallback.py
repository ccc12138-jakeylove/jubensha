import re

from jubensha.engine.perception import PerceptionView


def _bigrams(text: str) -> set[str]:
    normalized = "".join(re.findall(r"[\w\u4e00-\u9fff]+", text.lower()))
    return {normalized[index:index + 2] for index in range(len(normalized) - 1)}


def safe_response_with_source(perception: PerceptionView, question: str) -> tuple[str, list[str]]:
    candidates = [(item["surface_text"], [item["clue_id"]]) for item in perception.known_clues]
    candidates += [(item["text"], [item["statement_id"]])
                   for item in perception.known_statements]
    candidates += [(observation, [event["event_id"]]) for event in perception.known_events
                   for observation in event["observable"]]
    known_events = {item["event_id"] for item in perception.known_events}
    candidates += [(belief["statement"], [belief["source_event_id"]]
                    if belief["source_event_id"] in known_events else [])
                   for belief in perception.false_beliefs]
    if not candidates:
        return "我没留意到更多细节。", []
    topic = _bigrams(question)
    scored = [(len(topic.intersection(_bigrams(text))), text, ids) for text, ids in candidates]
    score, text, evidence_ids = max(scored, key=lambda item: item[0])
    if score == 0:
        return "这件事我没亲眼看见，不敢乱说。", []
    return f"我只知道：{text}", evidence_ids


def safe_response(perception: PerceptionView, question: str) -> str:
    return safe_response_with_source(perception, question)[0]
