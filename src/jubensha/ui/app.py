import json
import os
from pathlib import Path
from uuid import uuid4

import streamlit as st

from jubensha.engine.fsm import Phase
from jubensha.engine.loop import build_turn_graph, run_turn
from jubensha.engine.search import available_clues
from jubensha.engine.seats import current_seat
from jubensha.engine.board import relationship_dot, visible_relationships, clue_dot, timeline_rows
from jubensha.engine.recap import analyze_recap
from jubensha.engine.replay import reference_evidence, replay_at
from jubensha.engine.world import TruthStore
from jubensha.agents.referee import judge_submission
from jubensha.schema.events import EventType
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore
from jubensha.storage.scripts import ScriptStore
from jubensha.ui.library import show_library, show_review
from jubensha.ui.evals import show_evals


def fixture_path() -> Path:
    return Path(os.getenv("SCRIPT_FIXTURE", "fixtures/wugang_01.json"))


def main():
    st.set_page_config(page_title="剧本杀", layout="wide")
    fixture = Script.model_validate(json.loads(fixture_path().read_text(encoding="utf-8")))
    store = EventStore(os.getenv("GAME_DB", "game.db"))
    scripts = ScriptStore(store)
    scripts.register_fixture(fixture)
    view = st.query_params.get("view")
    if view == "library":
        show_library(fixture, store, scripts)
        return
    if view == "review":
        show_review(scripts, st.query_params.get("draft", ""))
        return
    if view == "eval":
        show_evals(fixture, store, scripts)
        return
    game_id = st.query_params.get("game")
    if not game_id:
        game_id = store.latest_game()
    if st.sidebar.button("剧本库"):
        st.query_params["view"] = "library"
        st.rerun()
    if st.sidebar.button("评测"):
        st.query_params["view"] = "eval"
        st.rerun()
    script_id = store.game_script_id(game_id) if game_id else fixture.script_id
    try:
        if script_id == fixture.script_id:
            script = fixture
        elif game_id and store.is_preview_game(game_id):
            script = scripts.load_preview(script_id)
            st.warning("草稿试玩：内容和结果尚未通过正式验收。")
        else:
            script = scripts.load_playable(script_id)
    except KeyError:
        # 对局引用的剧本已被删除（例如清理过剧本库）：丢弃失效的 game 参数回到开局页
        st.warning("上一局引用的剧本已不在库中，已回到开局页。")
        if "game" in st.query_params:
            del st.query_params["game"]
        st.stop()
    except ValueError as exc:
        st.error(str(exc))
        return
    st.title(script.title)
    if not game_id:
        if st.button("开局"):
            game_id = uuid4().hex
            store.create_game(game_id, script.script_id, script.acts[0].act_id)
            st.query_params["game"] = game_id
            st.rerun()
        return
    seat_id = "seat_1"
    try:
        state = store.load_for_seat(game_id, seat_id, script.acts[0].search_points_budget)
    except (KeyError, PermissionError):
        st.error("对局不存在")
        return
    seat = current_seat(state, seat_id)
    ordered_acts = sorted(script.acts, key=lambda act: act.order)
    current_act = next(act for act in ordered_acts if act.act_id == state.act_id)
    is_last_act = current_act == ordered_acts[-1]
    graph = build_turn_graph(script, store)

    def play(action: str, **kwargs):
        try:
            run_turn(graph, store, script, {"game_id": game_id, "action": action,
                                            "actor_seat_id": seat_id, **kwargs})
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    def dialogue(phase: Phase):
        for event in store.events_for_seat(game_id, seat_id):
            if event.phase != phase or event.type not in (EventType.PLAYER_INPUT, EventType.NPC_SPEECH, EventType.DM_NARRATION):
                continue
            if event.type == EventType.DM_NARRATION:
                if event.payload.get("director_level"):
                    st.chat_message("assistant").write(f"主持人：{event.payload['text']}")
                continue
            name = "你" if event.type == EventType.PLAYER_INPUT else script.characters[event.payload["role_id"]].display_name
            st.chat_message("user" if name == "你" else "assistant").write(f"{name}：{event.payload['text']}")

    st.caption(f"{state.phase.value.upper()} · 第 {state.turn} 回合 · 对局 {game_id[:8]}")
    if state.phase not in (Phase.ENTRY, Phase.RECAP, Phase.END):
        st.sidebar.metric("剩余搜证点", seat.search_points)
    if state.phase == Phase.ENTRY:
        st.write(script.acts[0].public_narrative)
        if st.button("开始阅读"):
            play("begin")
    elif state.phase == Phase.READ:
        st.subheader("案件简报")
        st.write(next(act for act in script.acts if act.act_id == state.act_id).public_narrative)
        for character in script.characters.values():
            st.write(f"**{character.display_name}**：{character.public_profile}")
        if st.button("读完，进入公聊"):
            play("read_done")
    elif state.phase == Phase.ACT_OPEN:
        st.subheader("公聊")
        dialogue(Phase.ACT_OPEN)
        role_id = st.selectbox("询问对象", ["", *script.characters],
                               format_func=lambda x: "面向全场" if not x else script.characters[x].display_name)
        with st.form("talk", clear_on_submit=True):
            question = st.text_input("你想问什么")
            submitted = st.form_submit_button("询问")
        if submitted and question.strip():
            play("talk", role_id=role_id, text=question)
        act = next(act for act in script.acts if act.act_id == state.act_id)
        col1, col2, col3 = st.columns(3)
        if col1.button("进入搜证", disabled=Phase.SEARCH not in act.allowed_phases):
            play("enter_search")
        if col2.button("进入私聊",
                       disabled=(Phase.PRIVATE not in act.allowed_phases or not role_id
                                 or state.private_chats_used >= act.private_chat_budget)):
            play("enter_private", role_id=role_id)
        if col3.button("进入对质", disabled=Phase.CONFRONT not in act.allowed_phases):
            play("enter_confront")
    elif state.phase == Phase.SEARCH:
        st.subheader("搜证")
        location_id = st.selectbox("地点", list(script.locations),
                                   format_func=lambda x: script.locations[x].display_name)
        st.write(script.locations[location_id].description)
        candidates = available_clues(script, state, location_id)
        if script.search_mode == "location_bundle":
            st.caption(f"本地点可发现线索：{len(candidates)} · 消耗 1 点")
        else:
            st.caption(f"本地点剩余次数：{max(0, script.locations[location_id].capacity_per_act - state.search_counts.get(location_id, 0))}")
        if candidates:
            if script.search_mode == "location_bundle":
                if st.button("搜查地点"):
                    play("search_bundle", location_id=location_id)
            else:
                clue_id = st.selectbox("搜查目标", [clue.clue_id for clue in candidates],
                                       format_func=lambda key: f"{script.clues[key].search_label or script.clues[key].display_name} · {script.clues[key].search_cost} 点")
                if st.button("搜查"):
                    play("search", location_id=location_id, clue_id=clue_id)
        else:
            st.info("这里没有当前可搜查的线索。")
        owned_here = [clue for clue in script.clues.values()
                      if clue.location_id == location_id
                      and clue.clue_id in set(state.public_clue_ids + seat.private_clue_ids)]
        if owned_here:
            st.subheader("本地点已发现")
            for clue in owned_here:
                with st.expander(clue.display_name):
                    st.write(clue.surface_text)
        if st.button("返回公聊"):
            play("leave_search")
    elif state.phase == Phase.PRIVATE:
        st.subheader("私聊")
        dialogue(Phase.PRIVATE)
        role_id = state.private_role_id
        st.write(script.characters[role_id].display_name)
        with st.form("private_talk", clear_on_submit=True):
            question = st.text_input("私聊内容")
            submitted = st.form_submit_button("询问")
        if submitted and question.strip():
            play("private_talk", role_id=role_id, text=question)
        if st.button("结束私聊"):
            play("leave_private")
    elif state.phase == Phase.CONFRONT:
        st.subheader("对质与指认" if current_act.requires_vote else "对质")
        dialogue(Phase.CONFRONT)
        role_id = st.selectbox("你指认谁", list(script.characters),
                               format_func=lambda x: script.characters[x].display_name)
        owned = list(dict.fromkeys(state.public_clue_ids + seat.private_clue_ids))
        evidence = st.multiselect("关键证据", owned,
                                  format_func=lambda x: script.clues[x].display_name)
        with st.form("confront_talk", clear_on_submit=True):
            question = st.text_input("对质内容")
            confronted = st.form_submit_button("追问")
        if confronted and question.strip():
            play("confront_talk", role_id=role_id, text=question, evidence_ids=evidence)
        if current_act.requires_vote:
            motive = st.text_area("动机与推理")
            if st.button("提交指认"):
                play("vote", role_id=role_id, motive=motive, evidence_ids=evidence)
        else:
            st.info("本幕不进行指认，对质结束后进入下一幕。")
            if st.button("进入下一幕"):
                play("next_act")
        if st.button("继续公聊"):
            play("leave_confront")
    elif state.phase == Phase.VOTE:
        st.write("指认已记录。")
        if is_last_act:
            if st.button("查看复盘"):
                play("recap")
        elif st.button("进入下一幕"):
            play("next_act")
    elif state.phase in (Phase.RECAP, Phase.END):
        truth = TruthStore(script).recap()
        culprit_ids = {key for key, c in script.characters.items() if c.is_culprit}
        judgment = judge_submission(script, state)
        st.subheader("玩家推理与真相")
        st.write(f"你的指认：{script.characters[state.vote_role_id].display_name if state.vote_role_id else '未提交'}")
        st.write(f"真实凶手：{'、'.join(truth['culprits'])}")
        st.write(f"凶手判断：{'正确' if state.vote_role_id in culprit_ids else '错误'}")
        st.write(f"判分：{judgment.score:g}/{judgment.max_score:g}")
        for key, correct in judgment.outcomes.items():
            st.write(f"{key}：{'符合' if correct else '未符合'}")
        st.write(f"你的动机判断：{state.vote_motive or '未填写'}")
        st.write("你的证据：" + ("、".join(script.clues[c].display_name for c in state.vote_evidence_ids) or "未选择"))
        analysis = analyze_recap(script, state, store.events_for_seat(game_id, seat_id), seat_id)
        st.subheader("证据链")
        st.write("参考路径：" + (" → ".join(script.clues[key].display_name for key in analysis["reference_clue_ids"]) or "暂无"))
        st.write("未发现：" + ("、".join(script.clues[key].display_name for key in analysis["missing_clue_ids"]) or "无"))
        st.write("已发现但未提交：" + ("、".join(script.clues[key].display_name for key in analysis["not_submitted_clue_ids"]) or "无"))
        st.subheader("完整时间线")
        for event in truth["timeline"]:
            st.write(f"{event['event_id']} · t={event['t_start']}：{event['action']}")
        st.subheader("秘密与线索")
        for secret in script.secrets.values():
            st.write(f"{secret.secret_id}：{secret.content}")
        with st.expander("事件回放", expanded=False):
            all_events = store.events(game_id)
            if all_events:
                seq = st.slider("事件序号", 0, all_events[-1].seq, all_events[-1].seq)
                author_token = os.getenv("AUTHOR_TOKEN")
                entered_token = st.text_input("作者令牌", type="password") if author_token else ""
                author_view = bool(author_token and entered_token == author_token)
                perspectives = [seat_id, *script.characters] if author_view else [seat_id]
                perspective = st.selectbox("视角", perspectives,
                                            format_func=lambda key: "玩家" if key == seat_id else script.characters[key].display_name)
                if perspective != seat_id:
                    scripts.audit("author", "replay_perspective", game_id, f"{perspective}@{seq}")
                historic, visible, perception = replay_at(script, store, game_id, seq, perspective)
                st.write(f"第 {historic.turn} 回合 · {historic.phase.value.upper()}")
                for event in visible:
                    if event.type in (EventType.PLAYER_INPUT, EventType.NPC_SPEECH, EventType.DM_NARRATION):
                        st.write(f"#{event.seq} {event.type.value}：{event.payload.get('text', '')}")
                        if event.type == EventType.NPC_SPEECH and event.payload.get("evidence_ids"):
                            st.caption("依据：" + "、".join(event.payload["evidence_ids"]))
                    elif event.type == EventType.CLUE_FOUND:
                        st.write(f"#{event.seq} 线索：{script.clues[event.payload['clue_id']].display_name}")
                if perception is not None:
                    st.write("该时刻角色认知")
                    st.json(perception.model_dump())
            player_clues = set(state.public_clue_ids) | set(seat.private_clue_ids)
            reference = reference_evidence(script)
            st.write("IR 参考证据：" + "、".join(script.clues[key].display_name for key in reference))
            st.write("已获得：" + "、".join(script.clues[key].display_name for key in reference if key in player_clues))
            st.write("未获得：" + "、".join(script.clues[key].display_name for key in reference if key not in player_clues))
        if state.phase == Phase.RECAP and st.button("结束本局"):
            play("end")
    if state.phase not in (Phase.ENTRY, Phase.READ):
        st.sidebar.subheader("线索板")
        for clue_id in dict.fromkeys(state.public_clue_ids + seat.private_clue_ids):
            clue = script.clues[clue_id]
            with st.sidebar.expander(clue.display_name):
                st.write(clue.surface_text)
        with st.expander("推理板"):
            relations_tab, clues_tab, timeline_tab = st.tabs(["关系图", "证据链", "时间线"])
            with relations_tab:
                st.graphviz_chart(relationship_dot(script, state, seat_id), width="stretch")
                relation_labels = {"lover": "恋人", "kin": "亲属", "debtor": "债务",
                                   "rival": "对手", "employer": "雇佣", "stranger": "陌生人"}
                def name(role_id: str) -> str:
                    return script.characters[role_id].display_name if role_id in script.characters else role_id.replace("_", " ")
                relations = [{"人物": name(item.from_role),
                              "关系": relation_labels.get(item.type, item.type),
                              "对象": name(item.to_role)}
                             for item in visible_relationships(script, state, seat_id)]
                if relations:
                    st.dataframe(relations, hide_index=True, width="stretch")
            with clues_tab:
                st.graphviz_chart(clue_dot(script, state, seat_id), width="stretch")
            with timeline_tab:
                rows = timeline_rows(store.events_for_seat(game_id, seat_id))
                if rows:
                    st.dataframe(rows, hide_index=True, width="stretch")
    if st.sidebar.button("新开一局"):
        new_id = uuid4().hex
        store.create_game(new_id, script.script_id, script.acts[0].act_id,
                          is_preview=bool(game_id and store.is_preview_game(game_id)))
        st.query_params["game"] = new_id
        st.rerun()


if __name__ == "__main__":
    main()
