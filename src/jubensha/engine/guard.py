import re
import json
from difflib import SequenceMatcher

from jubensha.engine.perception import PerceptionView
from jubensha.schema.ir import Script
from jubensha.llm.gateway import configured, generate
from jubensha.storage.events import EventStore


def _plain(text: str) -> str:
    return "".join(re.findall(r"[\w\u4e00-\u9fff]+", text.lower()))


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


def check_npc_output(script: Script, perception: PerceptionView, response: str) -> bool:
    allowed_events = {item["event_id"] for item in perception.known_events}
    allowed_clues = {item["clue_id"] for item in perception.known_clues}
    for identifier in re.findall(r"\b(?:E|C|S)\d{2,}\b", response):
        if identifier.startswith("S") or identifier not in allowed_events | allowed_clues:
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
    surfaces = [{"fact": item.fact, "paraphrases": item.paraphrases,
                 "implications": item.implications} for item in script.leak_surfaces.values()]
    messages = [
        {"role": "system", "content": "判断候选台词是否直接、换词或暗示泄露任一禁止事实。只输出 PASS 或 BLOCK；不确定时输出 BLOCK。"},
        {"role": "user", "content": json.dumps({"forbidden": surfaces, "candidate": response}, ensure_ascii=False)},
    ]
    try:
        verdict = generate(store, game_id, "guard_leak", "guard.leak.v1", messages)
    except Exception:
        return False
    return verdict.strip().upper() == "PASS"
