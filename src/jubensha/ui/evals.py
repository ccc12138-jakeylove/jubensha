import json

import streamlit as st

from jubensha.eval.harness import run_eval
from jubensha.llm.gateway import configured
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore
from jubensha.storage.evals import EvalStore
from jubensha.storage.scripts import ScriptStore


def show_evals(fixture: Script, events: EventStore, scripts: ScriptStore) -> None:
    st.title("评测")
    published = [item for item in scripts.list_scripts() if item["status"] == "published"]
    options = [fixture.script_id, *(item["script_id"] for item in published if item["script_id"] != fixture.script_id)]
    script_id = st.selectbox("剧本", options,
                             format_func=lambda key: fixture.title if key == fixture.script_id else next(
                                 item["title"] for item in published if item["script_id"] == key))
    script = fixture if script_id == fixture.script_id else scripts.load_published(script_id)
    games = st.number_input("每种策略的局数", min_value=1, max_value=20, value=5, step=1)
    live = st.checkbox("使用模型", disabled=not configured())
    if st.button("运行评测"):
        with st.spinner("正在运行对局与探针"):
            try:
                run_eval(script, events, games_per_persona=int(games), live_model=live)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    runs = EvalStore(events).list_runs(script_id)
    for run in runs:
        with st.expander(f"{run['created_at']} · {run['status']} · {run['run_id'][:8]}"):
            metrics = json.loads(run["metrics_json"])
            st.dataframe([{"指标": key, "结果": value} for key, value in metrics.items()],
                         hide_index=True, use_container_width=True)
            cases = EvalStore(events).cases(run["run_id"])
            if cases:
                st.write("失败与探针案例")
                st.dataframe([{"类别": item["category"], "命中": bool(item["hit"]),
                               "输入": item["input_json"], "实际": item["actual_json"]}
                              for item in cases], hide_index=True, use_container_width=True)
