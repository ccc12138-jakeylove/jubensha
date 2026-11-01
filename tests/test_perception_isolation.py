import json

from jubensha.engine.perception import build_perception


def test_perception_isolation(script, state):
    all_events = {e.event_id for e in script.truth_events}
    for role_id, knowledge in script.knowledge.items():
        serialized = build_perception(script, state, role_id).model_dump_json()
        obj = json.loads(serialized)
        assert "truth" not in serialized.lower()
        assert "is_culprit" not in serialized
        for forbidden in all_events - set(knowledge.knows_event_ids):
            assert forbidden not in serialized
        for forbidden in set(script.clues) - set(knowledge.knows_clue_ids):
            assert forbidden not in serialized
        for forbidden in set(script.secrets):
            assert forbidden not in serialized
        assert obj["role_id"] == role_id


def test_truth_probe_is_absent(script, state):
    secret = script.secrets["S02"].content
    assert secret not in build_perception(script, state, "lin_suyun").model_dump_json()
