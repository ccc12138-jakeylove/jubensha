import os
import time
import json
from hashlib import sha256

if not os.getenv("LLM_MODEL") or os.getenv("LLM_MODEL", "").startswith(("ollama/", "ollama_chat/")):
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from litellm import completion, completion_cost

from jubensha.storage.events import EventStore


def configured() -> bool:
    return bool(os.getenv("LLM_MODEL"))


def model_for(node: str) -> tuple[str, str]:
    if node == "compiler_repair" and os.getenv("LLM_MODEL_STRONG"):
        return os.environ["LLM_MODEL_STRONG"], "repair_escalation"
    route = ("COMPILER" if node.startswith("compiler") else
             "NPC" if node.startswith("npc") else
             "JUDGE" if node.startswith("judge") or node == "eval_judge" else
             "SIMULATOR" if node.startswith("simulator") or node in ("search_plan", "vote_plan") else
             "GUARD" if node.startswith("guard") else "DEFAULT")
    selected = os.getenv(f"LLM_MODEL_{route}") if route != "DEFAULT" else None
    return selected or os.environ["LLM_MODEL"], route.lower()


def generate(store: EventStore, game_id: str, node: str, prompt_version: str,
             messages: list[dict[str, str]], max_tokens: int = 180,
             json_mode: bool = False) -> str:
    model, route_reason = model_for(node)
    request_hash = sha256(json.dumps({"version": prompt_version, "messages": messages},
                                     ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    cache_key = sha256(f"{model}:{request_hash}:{max_tokens}:{json_mode}".encode()).hexdigest()
    cacheable = node.startswith("compiler")
    start = time.perf_counter()
    cached = store.cache_get(cache_key) if cacheable else None
    if cached is not None:
        store.trace(game_id, node, prompt_version, 0, 0, 0, 0.0,
                    model=model, prompt_hash=request_hash, route_reason=route_reason,
                    cache_hit=True)
        return cached
    try:
        options = {"extra_body": {"think": False}} if model.startswith(("ollama/", "ollama_chat/")) else {}
        if json_mode:
            options["response_format"] = {"type": "json_object"}
        response = completion(model=model, messages=messages,
                              api_key=os.getenv("LLM_API_KEY") or None,
                              api_base=os.getenv("LLM_BASE_URL") or None,
                              max_tokens=max_tokens,
                              temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")), **options)
        content = response.choices[0].message.content or ""
        usage = response.usage
        try:
            cost_usd = completion_cost(completion_response=response)
        except Exception:
            cost_usd = None
        if cacheable and content:
            store.cache_put(cache_key, content)
        return content
    finally:
        elapsed = round((time.perf_counter() - start) * 1000)
        store.trace(game_id, node, prompt_version,
                    getattr(locals().get("usage"), "prompt_tokens", 0) or 0,
                    getattr(locals().get("usage"), "completion_tokens", 0) or 0,
                    elapsed, locals().get("cost_usd"), model=model,
                    prompt_hash=request_hash, route_reason=route_reason)
