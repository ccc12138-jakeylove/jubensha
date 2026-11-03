import re
import json
from difflib import SequenceMatcher

from jubensha.engine.perception import PerceptionView
from jubensha.schema.ir import Script
from jubensha.llm.gateway import configured, generate
from jubensha.storage.events import EventStore


def _plain(text: str) -> str:
    return "".join(re.findall(r"[\w\u4e00-\u9fff]+", text.lower()))


def _chinese_number(value: str) -> int | None:
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if "十" in value:
        left, right = value.split("十", 1)
        if left and left not in digits or right and right not in digits:
            return None
        return (digits[left] if left else 1) * 10 + (digits[right] if right else 0)
    if all(char in digits for char in value):
        number = 0
        for char in value:
            number = number * 10 + digits[char]
        return number
    return None


def _times(text: str) -> set[tuple[int, int]]:
    result = {(int(hour), int(minute)) for hour, minute in
              re.findall(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", text)}
    for hour_text, minute_text in re.findall(
        r"([零〇一二两三四五六七八九十]{1,3})点([零〇一二两三四五六七八九十]{1,3})分", text):
        hour, minute = _chinese_number(hour_text), _chinese_number(minute_text)
        if hour is not None and minute is not None and hour < 24 and minute < 60:
            result.add((hour, minute))
            if hour < 12 and any(word in text for word in ("夜", "晚")):
                result.add((hour + 12, minute))
    return result


def blocked_input(text: str) -> bool:
    normalized = _plain(text)
    return any(term in normalized for term in (
        "忽略之前", "系统提示", "开发者模式", "你是ai", "你是人工智能",
        "假装你是旁白", "联网查询", "上网查资料", "ignorepreviousinstructions",
        "systemprompt", "developerinstructions",
    ))


def _similar(phrase: str, response: str) -> bool:
    needle = _plain(phrase)
    haystack = _plain(response)
    if len(needle) < 6:
        return False
    if needle in haystack:
        return True
    if len(haystack) < 6:
        return False
    window_sizes = {max(6, len(needle) + offset) for offset in (-3, 0, 3)}
    for size in window_sizes:
        for start in range(0, max(1, len(haystack) - size + 1)):
            sample = haystack[start:start + size]
            if SequenceMatcher(None, needle, sample).ratio() >= 0.86:
                return True
    return False


def check_npc_output(script: Script, perception: PerceptionView, response: str,
                     question: str = "") -> bool:
    allowed_events = {item["event_id"] for item in perception.known_events}
    allowed_clues = {item["clue_id"] for item in perception.known_clues}
    for identifier in re.findall(r"\b(?:E|C|S)\d{2,}\b", response):
        if identifier.startswith("S") or identifier not in allowed_events | allowed_clues:
            return False
    if any(topic in response and topic not in question for topic in perception.forbidden_topics):
        return False
    allowed_text = json.dumps({
        "public": perception.public_summary,
        "events": perception.known_events,
        "clues": perception.known_clues,
        "statements": perception.known_statements,
        "beliefs": perception.false_beliefs,
        "lie_cues": perception.lie_cues,
    }, ensure_ascii=False)
    if not _times(response).issubset(_times(allowed_text)):
        return False
    for secret in script.secrets.values():
        if any(all(_plain(part) in _plain(response) for part in triple)
               for triple in secret.forbidden_claims):
            return False
    for surface in script.leak_surfaces.values():
        if any(_similar(phrase, response)
               for phrase in (surface.fact, *surface.paraphrases, *surface.implications)):
            return False
    return True


def semantic_leak_check(script: Script, response: str, store: EventStore, game_id: str) -> bool:
    if not configured():
        return True
    public_text = _plain(" ".join(
        [act.public_narrative for act in script.acts]
        + [character.public_profile for character in script.characters.values()]
        + [location.description for location in script.locations.values()]))
    public_bigrams = {public_text[index:index + 2] for index in range(len(public_text) - 1)}
    candidate = _plain(response)
    candidate_bigrams = {candidate[index:index + 2] for index in range(len(candidate) - 1)}
    surfaces = []
    for item in script.leak_surfaces.values():
        phrases = [item.fact, *item.paraphrases, *item.implications]
        distinctive = set()
        for phrase in phrases:
            normalized = _plain(phrase)
            distinctive.update(normalized[index:index + 2] for index in range(len(normalized) - 1)
                               if normalized[index:index + 2] not in public_bigrams)
        if distinctive.intersection(candidate_bigrams):
            surfaces.append({"fact": item.fact, "paraphrases": item.paraphrases,
                             "implications": item.implications})
    if not surfaces:
        return True
    messages = [
        {"role": "system", "content": "判断候选台词是否直接、换词或暗示泄露任一禁止事实。只输出 PASS 或 BLOCK；不确定时输出 BLOCK。"},
        {"role": "user", "content": json.dumps({"forbidden": surfaces, "candidate": response}, ensure_ascii=False)},
    ]
    try:
        verdict = generate(store, game_id, "guard_leak", "guard.leak.v1", messages)
    except Exception:
        return False
    return verdict.strip().upper() == "PASS"
