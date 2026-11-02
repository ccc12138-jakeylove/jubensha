import json
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from jubensha.llm.gateway import configured
from jubensha.services.compile_worker import drain_eval_jobs
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore
from jubensha.storage.evals import EvalStore
from jubensha.storage.jobs import EvalJobs
from jubensha.storage.scripts import ScriptStore


@st.cache_resource
def eval_worker(db_path: str):
    jobs = EvalJobs(EventStore(db_path))
    return jobs, ThreadPoolExecutor(max_workers=1, thread_name_prefix="ui-eval")


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
    jobs, worker = eval_worker(events.path)
    if st.button("运行评测"):
        job = jobs.create(script.script_id, int(games), live)
        worker.submit(drain_eval_jobs, events, jobs, scripts, fixture)
        st.query_params["eval_job"] = job["job_id"]
        st.rerun()
    if st.button("刷新状态"):
        st.rerun()
    job_rows = jobs.list_jobs(script_id)
    if job_rows:
        st.dataframe([{"任务": item["job_id"][:8], "状态": item["status"],
                       "结果": item["run_id"] or item["error"] or ""}
                      for item in job_rows], hide_index=True, use_container_width=True)
    costs = events.trace_summary(script_id)
    if costs:
        st.subheader("模型调用")
        st.dataframe(costs, hide_index=True, use_container_width=True)
    runs = EvalStore(events).list_runs(script_id)
    if runs:
        models = sorted({json.loads(run["config_json"]).get("model_name", "offline") for run in runs})
        selected_model = st.selectbox("模型筛选", ["全部", *models])
        runs = [run for run in runs if selected_model == "全部"
                or json.loads(run["config_json"]).get("model_name", "offline") == selected_model]
    compare_ids = st.multiselect("对比运行", [run["run_id"] for run in runs], max_selections=2,
                                 format_func=lambda key: key[:8]) if runs else []
    if len(compare_ids) == 2:
        first, second = (json.loads(next(run["metrics_json"] for run in runs if run["run_id"] == key))
                         for key in compare_ids)
        st.dataframe([{"指标": key, "运行 1": first.get(key), "运行 2": second.get(key),
                       "变化": round(second[key] - first[key], 4)
                       if isinstance(first.get(key), (int, float)) and isinstance(second.get(key), (int, float))
                       else None}
                      for key in sorted(set(first) | set(second))],
                     hide_index=True, use_container_width=True)
    for run in runs:
        with st.expander(f"{run['created_at']} · {run['status']} · {run['run_id'][:8]}"):
            metrics = json.loads(run["metrics_json"])
            st.dataframe([{"指标": key, "结果": value} for key, value in metrics.items()],
                         hide_index=True, use_container_width=True)
            results = json.loads(run["results_json"])
            if results:
                st.write("逐局结果")
                st.dataframe(results, hide_index=True, use_container_width=True)
            cases = EvalStore(events).cases(run["run_id"])
            if cases:
                st.write("失败与探针案例")
                st.dataframe([{"类别": item["category"], "命中": bool(item["hit"]),
                               "输入": item["input_json"], "实际": item["actual_json"]}
                              for item in cases], hide_index=True, use_container_width=True)
