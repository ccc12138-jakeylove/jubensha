import pytest

from jubensha.engine.fsm import Phase, TRANSITIONS, transition


def test_all_transitions():
    for source in Phase:
        for target in Phase:
            if target in TRANSITIONS[source]:
                assert transition(source, target, last_act=target != Phase.READ or source != Phase.VOTE) == target
            else:
                with pytest.raises(ValueError):
                    transition(source, target)
    with pytest.raises(ValueError):
        transition(Phase.SEARCH, Phase.VOTE)
    with pytest.raises(ValueError):
        transition(Phase.VOTE, Phase.RECAP, last_act=False)
