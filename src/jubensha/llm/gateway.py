import os
import time

from litellm import completion

from jubensha.storage.events import EventStore


def configured() -> bool:
    return bool(os.getenv("LLM_MODEL"))


def generate(store: EventStore, game_id: str, node: str, prompt_version: str,
             messages: list[dict[str, str]], max_tokens: int = 180) -> str:
    model = os.environ["LLM_MODEL"]
    start = time.perf_counter()
    try:
        response = completion(model=model, messages=messages,
                              api_key=os.getenv("LLM_API_KEY") or None,
                              api_base=os.getenv("LLM_BASE_URL") or None,
                              max_tokens=max_tokens, temperature=0.3)
        content = response.choices[0].message.content or ""
        usage = response.usage
        return content
    finally:
        elapsed = round((time.perf_counter() - start) * 1000)
        store.trace(game_id, node, prompt_version,
                    getattr(locals().get("usage"), "prompt_tokens", 0) or 0,
                    getattr(locals().get("usage"), "completion_tokens", 0) or 0, elapsed)
