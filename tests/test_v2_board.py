from jubensha.engine.board import clue_dot, relationship_dot, timeline_rows
from jubensha.engine.fsm import Phase
from jubensha.schema.events import EventType, GameEvent


def test_relationship_board_reveals_private_links_only_after_evidence(script, state):
    before = relationship_dot(script, state, "seat_1")
    assert "employer" in before
    assert "debtor" not in before and "kin" not in before
    state.seats["seat_1"].private_clue_ids.append("C04")
    after = relationship_dot(script, state, "seat_1")
    assert "debtor" in after and "kin" not in after


def test_clue_board_and_timeline_use_visible_items(script, state):
    state.public_clue_ids.append("C01")
    dot = clue_dot(script, state, "seat_1")
    assert "C01" in dot and "C09" not in dot
    speech = GameEvent(seq=1, game_id="g", actor_seat_id="system", turn=1,
                       phase=Phase.ACT_OPEN, type=EventType.NPC_SPEECH,
                       payload={"text": "可见回答"}, visible_to=["*"])
    assert timeline_rows([speech]) == [{"回合": 1, "事件": "发言", "内容": "可见回答"}]
