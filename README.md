# 通用型剧本杀 AI Agent

单机剧本杀引擎与作者工作台。当前开发分支为 V2.0-beta；正式验收缺口见 [V2 状态](docs/V2_STATUS.md)。Python 3.11+，使用 uv。

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

V2 预览可单独设置 `GAME_DB=game_v2.db`，避免与固定 V1 服务共用数据。V2 API 使用 `uv run uvicorn jubensha.api.app:app --host 127.0.0.1 --port 8001`；`/api/v2/compile-jobs` 与 `/api/v2/eval-runs` 提交后台任务，轮询对应 ID。`AUTHOR_TOKEN` 控制角色认知回放视角。`LLM_MODEL_COMPILER`、`LLM_MODEL_NPC`、`LLM_MODEL_JUDGE`、`LLM_MODEL_GUARD` 可分别路由模型；`LLM_MODEL_STRONG` 只用于编译末次修复。三本完整授权 IR 准备好后，运行 `uv run python scripts/eval_gate.py fixture1.json fixture2.json fixture3.json` 做模型回归；该命令不能替代人工标注验收。

`uv run pytest` 运行测试。对局事件和 LangGraph 节点快照保存到当前目录的 `game.db`，URL 中的 `game` 参数用于续局。搜证按线索成本扣点，地点容量和前置线索由代码校验；每幕可用点数和私聊次数由 fixture 决定。

P2 中，NPC 只接收角色认知视图；声明随事件追加。输出先做确定性泄密检查；配置 `LLM_MODEL` 时再经 LiteLLM 做语义判定。未配置模型的测试只能验证结构隔离与静态拦截，不能代表真实模型的泄密率。
V1 默认 `NPC_GENERATION_MODE=grounded`：模型选择授权证据 ID，代码呈现事实；`freeform` 仅用于对照实验，需接受更高的幻觉与拦截风险。

P3 可在复盘页按事件序号回放，并切换玩家或 NPC 视角。历史对话摘要按视角写入 SQLite；当前默认 `CONTEXT_MODE=full`，`layered` 是超长局兜底，`auto` 可按字符近似预算自动切换。用 `uv run python scripts/compare_contexts.py` 比较同一局的两种上下文；配置模型后加 `--generate` 查看实际 token 与耗时。

P4 可在侧栏进入剧本库，上传 `.txt/.md/.docx/.pdf` 或完整 IR JSON。自然语言文件需要先配置模型；抽取失败和低置信度字段进入校对页。编辑 IR、解决校对项且质检无 blocker 后，才能发布并开局。

P5 公聊支持“面向全场”一次询问两位 NPC；导演只读取公开轨迹，安排 NPC 主动发言、公开线索反应及分级卡关提示。阶段和线索仍由代码裁定。

P6 用 `uv run python scripts/run_evals.py --output docs/V1_EVAL_REPORT.md` 运行四策略各 5 局离线评测；配置模型后加 `--live-model`。评测页可查看运行与案例。人工标注至少 20 组 `human,model` CSV 后，用 `uv run python scripts/calibrate_judge.py labels.csv` 检查 κ 是否达到 0.6。

P7 已验证同局双席的私密事件隔离、`custom` 胜利条件、未知事件回放和记忆后端替换接口。这些是 V1 扩展钩子；实时多人房间不在 V1 范围。复盘使用逐项判分，上传剧本在开局前显示检测到的内容提示。

单机 API 可用 `uv run uvicorn jubensha.api.app:app --host 127.0.0.1 --port 8000` 启动，接口文档位于 `/docs`。需要从局域网开放 API 时先设置 `API_TOKEN`，客户端发送 `Authorization: Bearer <token>`。Streamlit 是 V1 的主要界面。

## 更换 fixture

设置 `SCRIPT_FIXTURE` 为另一个符合 `Script` schema 的 JSON 文件路径，启动前先用 `Script.model_validate_json` 校验。引擎不读取固定剧本 ID 或固定地点 ID。
