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


def test_broad_accusation_gets_distinct_grounded_role_answers(script, state):
    question = "我觉得凶手在你们之中"
    responses = []
    for role_id in script.characters:
        perception = build_perception(script, state, role_id)
        response, evidence_ids = safe_response_with_source(perception, question)
        assert perception.display_name in response
        assert check_npc_output(script, perception, response, question)
        assert all(identifier in {item["event_id"] for item in perception.known_events}
                   for identifier in evidence_ids)
        responses.append(response)
    assert len(set(responses)) == len(responses)
