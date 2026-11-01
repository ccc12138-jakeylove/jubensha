import json
import os
from pathlib import Path
from uuid import uuid4

import streamlit as st

from jubensha.engine.fsm import Phase
from jubensha.engine.loop import build_turn_graph, run_turn
from jubensha.engine.search import available_clues
from jubensha.engine.world import TruthStore
from jubensha.schema.events import EventType
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore


def fixture_path() -> Path:
    return Path(os.getenv("SCRIPT_FIXTURE", "fixtures/wugang_01.json"))


def main():
    st.set_page_config(page_title="剧本杀", layout="wide")
    script = Script.model_validate(json.loads(fixture_path().read_text(encoding="utf-8")))
    store = EventStore(os.getenv("GAME_DB", "game.db"))
    game_id = st.query_params.get("game")
    if not game_id:
        game_id = store.latest_game()
    st.title(script.title)
    if not game_id:
        if st.button("开局"):
            game_id = uuid4().hex
            store.create_game(game_id, script.script_id, script.acts[0].act_id)
            st.query_params["game"] = game_id
            st.rerun()
        return
    try:
        state = store.load(game_id, script.acts[0].search_points_budget)
    except KeyError:
        st.error("对局不存在")
        return
    graph = build_turn_graph(script, store)

    def play(action: str, **kwargs):
        try:
            run_turn(graph, store, script, {"game_id": game_id, "action": action, **kwargs})
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    def dialogue(phase: Phase):
        for event in store.events(game_id):
            if event.phase != phase or event.type not in (EventType.PLAYER_INPUT, EventType.NPC_SPEECH):
                continue
            name = "你" if event.type == EventType.PLAYER_INPUT else script.characters[event.payload["role_id"]].display_name
            st.chat_message("user" if name == "你" else "assistant").write(f"{name}：{event.payload['text']}")

    st.caption(f"{state.phase.value.upper()} · 第 {state.turn} 回合 · 对局 {game_id[:8]}")
    if state.phase not in (Phase.ENTRY, Phase.RECAP, Phase.END):
        st.sidebar.metric("剩余搜证点", next(iter(state.seats.values())).search_points)
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
        role_id = st.selectbox("询问对象", list(script.characters),
                               format_func=lambda x: script.characters[x].display_name)
        with st.form("talk", clear_on_submit=True):
            question = st.text_input("你想问什么")
            submitted = st.form_submit_button("询问")
        if submitted and question.strip():
            play("talk", role_id=role_id, text=question)
        col1, col2, col3 = st.columns(3)
        if col1.button("进入搜证"):
            play("enter_search")
        act = next(act for act in script.acts if act.act_id == state.act_id)
        if col2.button("进入私聊", disabled=state.private_chats_used >= act.private_chat_budget):
            play("enter_private", role_id=role_id)
        if col3.button("进入对质"):
            play("enter_confront")
    elif state.phase == Phase.SEARCH:
        st.subheader("搜证")
        location_id = st.selectbox("地点", list(script.locations),
                                   format_func=lambda x: script.locations[x].display_name)
        st.write(script.locations[location_id].description)
        candidates = available_clues(script, state, location_id)
        st.caption(f"本地点剩余次数：{max(0, script.locations[location_id].capacity_per_act - state.search_counts.get(location_id, 0))}")
        if candidates:
            clue_id = st.selectbox("搜查目标", [clue.clue_id for clue in candidates],
                                   format_func=lambda key: f"{script.clues[key].display_name} · {script.clues[key].search_cost} 点")
            if st.button("搜查"):
                play("search", location_id=location_id, clue_id=clue_id)
        else:
            st.info("这里没有当前可搜查的线索。")
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
        st.subheader("对质与指认")
        dialogue(Phase.CONFRONT)
        role_id = st.selectbox("你指认谁", list(script.characters),
                               format_func=lambda x: script.characters[x].display_name)
        owned = list(dict.fromkeys(state.public_clue_ids + next(iter(state.seats.values())).private_clue_ids))
        evidence = st.multiselect("关键证据", owned,
                                  format_func=lambda x: script.clues[x].display_name)
        with st.form("confront_talk", clear_on_submit=True):
            question = st.text_input("对质内容")
            confronted = st.form_submit_button("追问")
        if confronted and question.strip():
            play("confront_talk", role_id=role_id, text=question, evidence_ids=evidence)
        motive = st.text_area("动机与推理")
        if st.button("提交指认"):
            play("vote", role_id=role_id, motive=motive, evidence_ids=evidence)
        if st.button("继续公聊"):
            play("leave_confront")
    elif state.phase == Phase.VOTE:
        st.write("指认已记录。")
        act_ids = [act.act_id for act in sorted(script.acts, key=lambda act: act.order)]
        if state.act_id == act_ids[-1]:
            if st.button("查看复盘"):
                play("recap")
        elif st.button("进入下一幕"):
            play("next_act")
    elif state.phase in (Phase.RECAP, Phase.END):
        truth = TruthStore(script).recap()
        culprit_ids = {key for key, c in script.characters.items() if c.is_culprit}
        st.subheader("玩家推理与真相")
        st.write(f"你的指认：{script.characters[state.vote_role_id].display_name if state.vote_role_id else '未提交'}")
        st.write(f"真实凶手：{'、'.join(truth['culprits'])}")
        st.write(f"凶手判断：{'正确' if state.vote_role_id in culprit_ids else '错误'}")
        st.write(f"你的动机判断：{state.vote_motive or '未填写'}")
        st.write("你的证据：" + ("、".join(script.clues[c].display_name for c in state.vote_evidence_ids) or "未选择"))
        st.subheader("完整时间线")
        for event in truth["timeline"]:
            st.write(f"{event['event_id']} · t={event['t_start']}：{event['action']}")
        st.subheader("秘密与线索")
        for secret in script.secrets.values():
            st.write(f"{secret.secret_id}：{secret.content}")
        if state.phase == Phase.RECAP and st.button("结束本局"):
            play("end")
    if state.phase not in (Phase.ENTRY, Phase.READ):
        st.sidebar.subheader("线索板")
        for clue_id in dict.fromkeys(state.public_clue_ids + next(iter(state.seats.values())).private_clue_ids):
            clue = script.clues[clue_id]
            st.sidebar.write(f"**{clue.display_name}** · {clue.surface_text}")
    if st.sidebar.button("新开一局"):
        new_id = uuid4().hex
        store.create_game(new_id, script.script_id, script.acts[0].act_id)
        st.query_params["game"] = new_id
        st.rerun()


if __name__ == "__main__":
    main()
