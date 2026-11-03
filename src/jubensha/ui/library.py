import json
from pathlib import Path
from uuid import uuid4

import streamlit as st

from jubensha.compiler.pipeline import compile_document
from jubensha.compiler.report import render_lint_report
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore
from jubensha.storage.scripts import ScriptStore


def _field_value(ir: dict, path: str):
    if "." not in path:
        return ir[path]
    root, item_id = path.split(".", 1)
    collection = ir[root]
    if isinstance(collection, dict):
        return collection[item_id]
    identifier = "event_id" if root == "truth_events" else "act_id"
    return next(item for item in collection if item.get(identifier) == item_id)


def _set_field_value(ir: dict, path: str, value) -> dict:
    updated = dict(ir)
    if "." not in path:
        updated[path] = value
        return updated
    root, item_id = path.split(".", 1)
    collection = ir[root]
    if isinstance(collection, dict):
        updated[root] = dict(collection) | {item_id: value}
    else:
        identifier = "event_id" if root == "truth_events" else "act_id"
        updated[root] = [value if item.get(identifier) == item_id else item
                         for item in collection]
    return updated


def _set_approvals(ir: dict, role_id: str, approvals: dict[str, bool]) -> dict:
    updated = dict(ir)
    knowledge = dict(ir["knowledge"])
    role = dict(knowledge[role_id])
    role["statements"] = [item | {"approved": approvals.get(item["statement_id"], item["approved"])}
                          for item in role.get("statements", [])]
    knowledge[role_id] = role
    updated["knowledge"] = knowledge
    return updated


def show_library(fixture: Script, events: EventStore, scripts: ScriptStore) -> None:
    st.title("剧本库")
    published = [item for item in scripts.list_scripts() if item["status"] == "published"]
    options = [fixture.script_id, *(item["script_id"] for item in published if item["script_id"] != fixture.script_id)]
    selected = st.selectbox("选择剧本", options,
                            format_func=lambda key: fixture.title if key == fixture.script_id else next(
                                item["title"] for item in published if item["script_id"] == key))
    if selected != fixture.script_id:
        for _, item, _ in scripts.reviews(selected):
            if item.conflict_type == "content_rating":
                st.warning(item.message)
    if st.button("开局"):
        script = fixture if selected == fixture.script_id else scripts.load_published(selected)
        game_id = uuid4().hex
        events.create_game(game_id, script.script_id, script.acts[0].act_id)
        st.query_params.clear()
        st.query_params["game"] = game_id
        st.rerun()
    st.subheader("导入剧本")
    upload = st.file_uploader("剧本文件", type=["txt", "md", "docx", "pdf", "json"])
    oversized = bool(upload and upload.size > 10_000_000)
    if oversized:
        st.error("文件超过 10 MB")
    authorized = st.checkbox("我确认拥有此剧本的使用权或已获授权")
    rights_source = st.text_input("授权来源", placeholder="本人原创或授权链接")
    rights_contact = st.text_input("授权联系人（选填）")
    if upload is not None and st.button("编译并保存草稿", disabled=oversized or not authorized or not rights_source.strip()):
        try:
            upload_id = scripts.save_upload(upload.name, upload.getvalue(),
                                            rights_source, rights_contact)
            draft = compile_document(upload.name, upload.getvalue(), events)
            draft_id = scripts.save_draft(draft, upload_id)
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
    if draft["status"] == "draft" and st.button("本机试玩", key=f"preview_{draft_id}"):
        try:
            script = scripts.load_preview(draft_id)
            game_id = uuid4().hex
            scripts.events.create_game(game_id, script.script_id, script.acts[0].act_id,
                                       is_preview=True)
            scripts.audit("author", "preview_draft", draft_id, game_id)
            st.query_params.clear()
            st.query_params["game"] = game_id
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if draft["status"] == "draft" and draft.get("source_upload_id"):
        with scripts.events.connect() as db:
            rights = db.execute("SELECT authorized_at,rights_source,distribution_scope FROM script_uploads WHERE upload_id=%s",
                                (draft["source_upload_id"],)).fetchone()
        if rights and rights["distribution_scope"] == "local_only":
            st.warning("此剧本仅限本地验证，不能确认发行授权或发布。")
        elif rights and not rights["authorized_at"]:
            st.warning("此草稿的改编与使用授权尚未确认")
            confirmed = st.checkbox("我确认拥有此剧本的改编与使用授权", key=f"rights_{draft_id}")
            source = st.text_input("授权依据", key=f"rights_source_{draft_id}")
            if st.button("确认授权", disabled=not confirmed or not source.strip()):
                scripts.confirm_rights(draft["source_upload_id"], source)
                scripts.audit("author", "confirm_rights", draft_id, source)
                st.rerun()
    provenance_items = draft["ir"].get("provenance", {})
    fields = []
    for key in draft["ir"]:
        if key in ("provenance", "parser_meta", "linter_report"):
            continue
        fields.append(key)
        fields.extend(path for path in provenance_items if path.startswith(key + "."))
    selected = st.selectbox("字段", fields)
    left, middle, right = st.columns([1.1, 1.2, 1])
    with left:
        st.subheader("原文")
        provenance = provenance_items.get(selected, {})
        span = provenance.get("source_span")
        if span and len(span) == 2:
            start, end = span
            st.caption(f"{provenance.get('source_doc', '')} · 页 {provenance.get('source_page') or '-'} · {start}:{end}")
            st.code(draft["source_text"][max(0, start - 240):min(len(draft["source_text"]), end + 240)])
        else:
            st.info("该字段尚无定位来源")
        with st.expander("完整原文"):
            st.text(draft["source_text"])
    with middle:
        st.subheader("结构化字段")
        st.caption(f"置信度 {provenance.get('confidence', 0):.0%}" if provenance else "待校对")
        field_key = f"field_{draft_id}_{selected}"
        edited_field = st.text_area("字段 JSON", json.dumps(_field_value(draft["ir"], selected), ensure_ascii=False, indent=2),
                                    height=440, key=field_key)
        if draft["status"] == "draft" and st.button("保存字段"):
            try:
                updated = _set_field_value(draft["ir"], selected, json.loads(edited_field))
                scripts.update_ir(draft_id, json.dumps(updated, ensure_ascii=False))
                del st.session_state[field_key]
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        with st.expander("完整 IR"):
            edited = st.text_area("结构化剧本", json.dumps(draft["ir"], ensure_ascii=False, indent=2),
                                  height=400)
            if draft["status"] == "draft" and st.button("保存完整 IR"):
                try:
                    scripts.update_ir(draft_id, edited)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
    with right:
        st.subheader("校验与引用")
        if selected == "clues" or selected.startswith("clues."):
            clues = draft["ir"].get("clues", {})
            items = ([(selected.split(".", 1)[1], _field_value(draft["ir"], selected))]
                     if selected.startswith("clues.") else clues.items() if isinstance(clues, dict) else [])
            for clue_id, clue in items:
                if isinstance(clue, dict):
                    st.write(f"{clue_id} → {clue.get('location_id', '?')} · 事件 {', '.join(clue.get('reveals_event_ids', []))} · 秘密 {', '.join(clue.get('reveals_secret_ids', []))}")
        for item_id, item, resolved in scripts.reviews(draft_id):
            if item.field_path not in (selected, "*") and not item.field_path.startswith(selected + "."):
                continue
            st.write(f"{item.conflict_type} · {item.field_path} · {item.message}")
            if item.source_span:
                start, end = item.source_span
                st.code(draft["source_text"][max(0, start - 120):min(len(draft["source_text"]), end + 120)])
            if not resolved and draft["status"] == "draft" and st.button("标记已处理", key=f"resolve_{item_id}"):
                scripts.resolve(draft_id, item_id)
                st.rerun()
        with st.expander("全部待处理项"):
            for _, item, resolved in scripts.reviews(draft_id):
                if not resolved:
                    st.write(f"{item.field_path} · {item.message}")
    revisions = scripts.revisions(draft_id)
    if revisions:
        with st.expander("版本记录"):
            for revision in revisions:
                st.write(f"#{revision['revision_id']} · {revision['created_at']} · {revision['diff_summary']}")
                if draft["status"] == "draft" and st.button("回退到此版本", key=f"rollback_{revision['revision_id']}"):
                    scripts.rollback(draft_id, revision["revision_id"])
                    st.rerun()
    statement_roles = [role_id for role_id, knowledge in draft["ir"].get("knowledge", {}).items()
                       if isinstance(knowledge, dict) and knowledge.get("statements")]
    if draft["status"] == "draft" and statement_roles:
        with st.expander("角色陈述校对"):
            role_id = st.selectbox("角色", statement_roles,
                                   format_func=lambda key: draft["ir"]["characters"][key]["display_name"])
            statements = draft["ir"]["knowledge"][role_id]["statements"]
            approvals = {}
            for item in statements:
                key = f"statement_{draft_id}_{item['statement_id']}"
                approvals[item["statement_id"]] = st.checkbox(
                    item["text"], value=bool(item["approved"]), key=key)
                if item.get("source_span"):
                    start, end = item["source_span"]
                    st.caption(f"{Path(item['source_doc']).name} · {start}:{end}")
            if st.button("保存角色陈述"):
                updated = _set_approvals(draft["ir"], role_id, approvals)
                scripts.update_ir(draft_id, json.dumps(updated, ensure_ascii=False))
                for item in statements:
                    st.session_state.pop(f"statement_{draft_id}_{item['statement_id']}", None)
                st.rerun()
    report = draft["ir"].get("linter_report")
    if report:
        st.subheader("质检报告")
        try:
            script = Script.model_validate(draft["ir"])
            st.markdown(render_lint_report(script, script.linter_report))
        except Exception:
            st.json(report)
    if draft["status"] == "draft" and st.button("发布剧本"):
        try:
            scripts.publish(draft_id)
            st.query_params.clear()
            st.query_params["view"] = "library"
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
