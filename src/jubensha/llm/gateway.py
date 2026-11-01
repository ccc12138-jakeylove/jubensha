import os
import time

if os.getenv("LLM_MODEL", "").startswith(("ollama/", "ollama_chat/")):
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from litellm import completion, completion_cost

from jubensha.storage.events import EventStore


def configured() -> bool:
    return bool(os.getenv("LLM_MODEL"))


def generate(store: EventStore, game_id: str, node: str, prompt_version: str,
             messages: list[dict[str, str]], max_tokens: int = 180,
             json_mode: bool = False) -> str:
    model = os.environ["LLM_MODEL"]
    start = time.perf_counter()
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
        return content
    finally:
        elapsed = round((time.perf_counter() - start) * 1000)
        store.trace(game_id, node, prompt_version,
                    getattr(locals().get("usage"), "prompt_tokens", 0) or 0,
                    getattr(locals().get("usage"), "completion_tokens", 0) or 0,
                    elapsed, locals().get("cost_usd"))
