from jubensha.engine.context import build_context


def test_context_budget(script, state):
    messages = build_context(script, state, next(iter(script.characters)), "案发时你在哪里？", [])
    assert len(messages) == 7
    assert all(f"L{i}" in messages[i - 1]["content"] for i in range(1, 7))
    assert sum(len(m["content"]) for m in messages) // 2 <= 3000
