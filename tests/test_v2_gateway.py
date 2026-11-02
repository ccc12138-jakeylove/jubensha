from types import SimpleNamespace

from jubensha.llm.gateway import generate, model_for
from jubensha.storage.events import EventStore


def test_compiler_model_route_and_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "ollama/small")
    monkeypatch.setenv("LLM_MODEL_STRONG", "ollama/strong")
    assert model_for("compiler_repair") == ("ollama/strong", "repair_escalation")
    calls = []
    def completion(**kwargs):
        calls.append(kwargs["model"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"value": 1}'))],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))
    monkeypatch.setattr("jubensha.llm.gateway.completion", completion)
    monkeypatch.setattr("jubensha.llm.gateway.completion_cost", lambda **kwargs: 0.01)
    store = EventStore(tmp_path / "cache.db")
    messages = [{"role": "user", "content": "extract this"}]
    assert generate(store, "g", "compiler_repair", "prompt.v2", messages, json_mode=True) == '{"value": 1}'
    assert generate(store, "g", "compiler_repair", "prompt.v2", messages, json_mode=True) == '{"value": 1}'
    assert calls == ["ollama/strong"]
    with store.connect() as db:
        rows = db.execute("SELECT model,prompt_hash,cache_hit FROM llm_traces ORDER BY id").fetchall()
    assert rows[0][0] == "ollama/strong" and len(rows[0][1]) == 64
    assert [row[2] for row in rows] == [0, 1]
    summary = store.trace_summary()
    assert summary[0]["calls"] == 2 and summary[0]["cache_hits"] == 1
