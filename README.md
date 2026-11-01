# 通用型剧本杀 AI Agent · P0

单幕 fixture 驱动的 Streamlit 对局。Python 3.11+，使用 uv。

## 安装

```powershell
uv sync
```

## 配置

```powershell
Copy-Item .env.example .env
```

设置 `LLM_MODEL`、`LLM_API_KEY`、`LLM_BASE_URL` 环境变量。也可不配置模型，此时 NPC 使用固定的角色内回避回答。`.env` 不会自动加载，可在 PowerShell 会话设置对应环境变量。

## 运行

```powershell
uv run streamlit run src/jubensha/ui/app.py
```

`uv run pytest` 运行测试。对局事件和 LangGraph 节点快照保存到当前目录的 `game.db`，URL 中的 `game` 参数用于续局。搜证按线索成本扣点，地点容量和前置线索由代码校验；每幕可用点数和私聊次数由 fixture 决定。

P2 中，NPC 只接收角色认知视图；声明随事件追加。输出先做确定性泄密检查；配置 `LLM_MODEL` 时再经 LiteLLM 做语义判定。未配置模型的测试只能验证结构隔离与静态拦截，不能代表真实模型的泄密率。

P3 可在复盘页按事件序号回放，并切换玩家或 NPC 视角。历史对话摘要按视角写入 SQLite；设置 `CONTEXT_MODE=full` 可临时使用全量对话上下文。用 `uv run python scripts/compare_contexts.py` 比较同一局的两种上下文大小；配置模型后加 `--generate` 对比回答与耗时。

## 更换 fixture

设置 `SCRIPT_FIXTURE` 为另一个符合 `Script` schema 的 JSON 文件路径，启动前先用 `Script.model_validate_json` 校验。引擎不读取固定剧本 ID 或固定地点 ID。
