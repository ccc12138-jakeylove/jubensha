from jubensha.agents.npc import respond
from jubensha.agents.fallback import safe_response_with_source
from jubensha.engine.fsm import Phase
from jubensha.engine.guard import check_npc_output
from jubensha.engine.perception import build_perception
from jubensha.eval.invariants import check_invariants
from jubensha.schema.events import EventType, GameEvent
from jubensha.schema.ir import KnowledgeStatement
from jubensha.storage.events import EventStore


def test_only_approved_sourced_statements_can_be_spoken_and_cited(script, state, tmp_path, monkeypatch):
    script = script.model_copy(deep=True)
    script.knowledge["chen_yanqiu"].statements = [
        KnowledgeStatement(statement_id="KCHEN_01", text="我见过停在22:55的怀表。",
                           approved=True, source_doc="role.txt", source_span=(0, 16)),
        KnowledgeStatement(statement_id="KCHEN_02", text="我知道不该透露的事。",
                           approved=False, source_doc="role.txt", source_span=(17, 29)),
    ]
    perception = build_perception(script, state, "chen_yanqiu")
    assert [item["statement_id"] for item in perception.known_statements] == ["KCHEN_01"]
    assert safe_response_with_source(perception, "你见过什么？")[1] == ["KCHEN_01"]
    monkeypatch.setattr("jubensha.agents.npc.configured", lambda: True)
    monkeypatch.setattr("jubensha.agents.npc.generate", lambda *args, **kwargs: '{"source_id":"KCHEN_01"}')
    response = respond(perception, "怀表几点停的？", [], EventStore(tmp_path / "statements.db"), "g")
    assert response.evidence_ids == ["KCHEN_01"]
    assert check_npc_output(script, perception, response.text, "怀表几点停的？")
    event = GameEvent(seq=1, game_id="g", actor_seat_id="system", turn=1,
                      phase=Phase.ACT_OPEN, type=EventType.NPC_SPEECH,
                      payload={"role_id": "chen_yanqiu", "text": response.text,
                               "evidence_ids": response.evidence_ids}, visible_to=["*"])
    assert not check_invariants(script, [event])
    bad = event.model_copy(update={"payload": event.payload | {"evidence_ids": ["KCHEN_02"]}})
    assert any("unauthorized NPC citation" in item for item in check_invariants(script, [bad]))


def test_future_act_statement_is_hidden_from_npc(script, state):
    script = script.model_copy(deep=True)
    script.acts.append(script.acts[0].model_copy(update={"act_id": "future_act", "order": 2}))
    script.knowledge["chen_yanqiu"].statements = [
        KnowledgeStatement(statement_id="NOW", text="当前幕已知。", approved=True,
                           act_id=script.acts[0].act_id),
        KnowledgeStatement(statement_id="LATER", text="下一幕才知道。", approved=True,
                           act_id="future_act"),
    ]
    assert [item["statement_id"] for item in build_perception(script, state, "chen_yanqiu").known_statements] == ["NOW"]
