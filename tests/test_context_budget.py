from jubensha.engine.context import build_context
from jubensha.engine.perception import build_perception


def test_context_budget(script, state):
    perception = build_perception(script, state, next(iter(script.characters)))
    messages = build_context(perception, "案发时你在哪里？", [])
    assert len(messages) == 7
    assert all(f"L{i}" in messages[i - 1]["content"] for i in range(1, 7))
    assert sum(len(m["content"]) for m in messages) // 2 <= 3000
