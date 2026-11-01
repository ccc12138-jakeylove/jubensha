from jubensha.agents.fallback import safe_response, safe_response_with_source
from jubensha.engine.guard import check_npc_output
from jubensha.engine.perception import build_perception


def test_fallback_uses_only_authorized_observation(script, state):
    perception = build_perception(script, state, "chen_yanqiu")
    response = safe_response(perception, "门闩有什么痕迹？")
    assert "门闩" in response
    assert script.secrets["S02"].content not in response
    assert check_npc_output(script, perception, response)
    assert safe_response_with_source(perception, "门闩有什么痕迹？")[1]


def test_fallback_without_relevant_fact_is_in_character(script, state):
    perception = build_perception(script, state, "a_dai")
    response = safe_response(perception, "码头的船票呢？")
    assert "不敢乱说" in response
