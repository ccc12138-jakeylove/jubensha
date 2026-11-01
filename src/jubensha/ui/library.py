import json
from uuid import uuid4

import streamlit as st

from jubensha.compiler.pipeline import compile_document
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore
from jubensha.storage.scripts import ScriptStore


def show_library(fixture: Script, events: EventStore, scripts: ScriptStore) -> None:
    st.title("剧本库")
    published = [item for item in scripts.list_scripts() if item["status"] == "published"]
    options = [fixture.script_id, *(item["script_id"] for item in published if item["script_id"] != fixture.script_id)]
    selected = st.selectbox("选择剧本", options,
                            format_func=lambda key: fixture.title if key == fixture.script_id else next(
                                item["title"] for item in published if item["script_id"] == key))
    if st.button("开局"):
        script = fixture if selected == fixture.script_id else scripts.load_published(selected)
        game_id = uuid4().hex
        events.create_game(game_id, script.script_id, script.acts[0].act_id)
        st.query_params.clear()
        st.query_params["game"] = game_id
        st.rerun()
    st.subheader("导入剧本")
    upload = st.file_uploader("剧本文件", type=["txt", "md", "docx", "pdf", "json"])
    authorized = st.checkbox("我确认拥有此剧本的使用权或已获授权")
    if upload is not None and st.button("编译并保存草稿", disabled=not authorized):
        try:
            draft = compile_document(upload.name, upload.getvalue(), events)
            draft_id = scripts.save_draft(draft)
            st.query_params["view"] = "review"
            st.query_params["draft"] = draft_id
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    drafts = [item for item in scripts.list_scripts() if item["status"] == "draft"]
    if drafts:
        st.subheader("待校对")
        for draft in drafts:
            if st.button(draft["title"], key=f"review_{draft['script_id']}"):
                st.query_params["view"] = "review"
                st.query_params["draft"] = draft["script_id"]
                st.rerun()


def show_review(scripts: ScriptStore, draft_id: str) -> None:
    try:
        draft = scripts.get_draft(draft_id)
    except KeyError:
        st.error("草稿不存在")
        return
    st.title(draft["title"])
    st.caption(draft["status"])
    left, right = st.columns(2)
    with left:
        st.subheader("IR")
        edited = st.text_area("结构化剧本", json.dumps(draft["ir"], ensure_ascii=False, indent=2), height=520)
        if draft["status"] == "draft" and st.button("保存修改"):
            try:
                scripts.update_ir(draft_id, edited)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with right:
        st.subheader("原文与校对")
        for item_id, item, resolved in scripts.reviews(draft_id):
            st.write(f"{item.conflict_type} · {item.field_path} · {item.message}")
            if item.source_span:
                start, end = item.source_span
                st.code(draft["source_text"][max(0, start - 120):end + 120])
            if not resolved and draft["status"] == "draft" and st.button("标记已处理", key=f"resolve_{item_id}"):
                scripts.resolve(draft_id, item_id)
                st.rerun()
    report = draft["ir"].get("linter_report")
    if report:
        st.subheader("质检报告")
        st.json(report)
    if draft["status"] == "draft" and st.button("发布剧本"):
        try:
            scripts.publish(draft_id)
            st.query_params.clear()
            st.query_params["view"] = "library"
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
