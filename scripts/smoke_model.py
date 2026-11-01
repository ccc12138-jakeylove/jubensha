import json
import os
from uuid import uuid4

from jubensha.engine.loop import build_turn_graph, run_turn
from jubensha.llm.gateway import configured
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore


if not configured():
    raise SystemExit("LLM_MODEL is required")
script = Script.model_validate_json(open(os.getenv("SCRIPT_FIXTURE", "fixtures/wugang_01.json"), encoding="utf-8").read())
store = EventStore(os.getenv("GAME_DB", "model_smoke.db"))
game_id = uuid4().hex
store.create_game(game_id, script.script_id, script.acts[0].act_id)
graph = build_turn_graph(script, store)
for action in ("begin", "read_done"):
    run_turn(graph, store, script, {"game_id": game_id, "action": action})
role_id = next(iter(script.characters))
result = run_turn(graph, store, script, {"game_id": game_id, "action": "talk",
                                             "role_id": role_id, "text": "案发时你在哪里？"})
with store.connect() as db:
    traces = [dict(row) for row in db.execute("SELECT node,prompt_version,input_tokens,output_tokens,latency_ms FROM llm_traces WHERE game_id=?",
                                               (game_id,))]
print(json.dumps({"game_id": game_id, "reply": result.get("reply", ""),
                  "leak_blocked": result.get("leak_blocked", False), "traces": traces}, ensure_ascii=False))
