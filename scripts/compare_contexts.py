import argparse
import json
import os
import time
from pathlib import Path

from jubensha.engine.context import build_context, context_size
from jubensha.engine.memory import summaries_for_context
from jubensha.engine.perception import build_perception
from jubensha.llm.gateway import configured, generate
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore
from jubensha.storage.memory import SummaryStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", help="Game ID; defaults to latest game")
    parser.add_argument("--role", help="NPC role ID; defaults to first role")
    parser.add_argument("--topic", default="案发时你看见了什么？")
    parser.add_argument("--generate", action="store_true", help="Generate both replies through LiteLLM")
    args = parser.parse_args()
    script = Script.model_validate_json(Path(os.getenv("SCRIPT_FIXTURE", "fixtures/wugang_01.json")).read_text(encoding="utf-8"))
    store = EventStore(os.getenv("GAME_DB", "game.db"))
    game_id = args.game or store.latest_game()
    if game_id is None:
        parser.error("No game exists in the database")
    role_id = args.role or next(iter(script.characters))
    state = store.load(game_id, script.acts[0].search_points_budget)
    events = store.events(game_id)
    perception = build_perception(script, state, role_id)
    public, role = summaries_for_context(SummaryStore(store), game_id, role_id,
                                         events, perception, args.topic)
    contexts = {
        "full": build_context(perception, args.topic, events, mode="full"),
        "layered": build_context(perception, args.topic, events,
                                 public_summary=public, role_summary=role, mode="layered"),
    }
    result = {mode: {"estimated_input_tokens": context_size(messages)}
              for mode, messages in contexts.items()}
    if args.generate:
        if not configured():
            parser.error("LLM_MODEL is required with --generate")
        for mode, messages in contexts.items():
            started = time.perf_counter()
            result[mode]["reply"] = generate(store, game_id, f"ab_{mode}", "npc.ab.v1", messages)
            result[mode]["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
