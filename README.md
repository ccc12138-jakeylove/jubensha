# 通用型剧本杀 AI Agent

单机剧本杀引擎与作者工作台。当前开发分支为 V2.0-beta；正式验收缺口见 [V2 状态](docs/V2_STATUS.md)。Python 3.11+，使用 uv，数据存储为 PostgreSQL 15+（单机也需要数据库实例）。

## 安装

```powershell
uv sync
```

先准备一个可连的 PostgreSQL 实例并建库（如 `createdb jubensha`），连接串写进 `.env` 的 `PG_DSN`；启动时会自动建表，无需手动执行 DDL。

## 配置

```bash
cp .env.example .env
```

在 `.env` 中按 `KEY=VALUE` 格式设置 `PG_DSN`、`LLM_MODEL`、`LLM_API_KEY`、`LLM_BASE_URL`，不要只放一行裸密钥。百炼示例为 `LLM_MODEL=openai/qwen3.7-plus` 与 `LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`；API Key 所属地区需与地址匹配。`.env` 由 `src/jubensha/__init__.py` 在包导入时加载，已在 shell 或 IDE 中设置的同名环境变量优先。未配置模型时 NPC 使用按角色公开身份区分的安全回避回答。

## 运行

```powershell
uv run streamlit run src/jubensha/ui/app.py
```

## React 前端（介绍页 + 对局台）

`frontend/` 是 React + Vite 站点，`http://127.0.0.1:8100` 一个地址同时提供介绍页与可玩的对局台，后端直接复用 `jubensha.api.app` 的对局路由，不重写任何回合规则。

```bash
cd frontend
npm ci && npm run build
cd ..
uv run uvicorn jubensha.web.app:app --host 127.0.0.1 --port 8100
```

- 入口：首屏「现在开局」或导航「进入对局」，地址变为 `/#play`，刷新后仍停在原页面
- 对局台可选择已发布剧本，支持开局、读本、公聊、搜证、私聊、对质、按幕投票及复盘；阶段流转由后端 FSM 裁定
- 介绍页提供主题切换、角色公开简介和预约表单；未获得的线索、真相时间线和无对局指认接口不会公开
- 公开展示接口：`GET /api/show/scripts`、`GET /api/show/script`、`GET /api/show/games/{game_id}/act`、`GET /api/show/search-options`、`POST /api/show/signup`
- 对外站点的作者接口需要 `AUTHOR_TOKEN`（Bearer），未配置时返回 503。公开玩家 API 目前仍是单席位模型，应保持 `127.0.0.1` 绑定；不要把此版本直接暴露到互联网。独立作者 API 的 `API_TOKEN` 会同时保护玩家路由，不适合直接嵌入浏览器
- 开发：`cd frontend && npm run dev`（5173，`/api` 代理到 8100）

V2 预览可单独设置 `PG_SCHEMA=jubensha_v2`（或指向另一个库），避免与固定 V1 服务共用数据。V2 API 使用 `uv run uvicorn jubensha.api.app:app --host 127.0.0.1 --port 8001`；`/api/v2/compile-jobs` 与 `/api/v2/eval-runs` 提交后台任务，轮询对应 ID。`AUTHOR_TOKEN` 控制角色认知回放视角。`LLM_MODEL_COMPILER`、`LLM_MODEL_NPC`、`LLM_MODEL_JUDGE`、`LLM_MODEL_GUARD` 可分别路由模型；`LLM_MODEL_STRONG` 只用于编译末次修复。三本完整授权 IR 准备好后，运行 `uv run python scripts/eval_gate.py fixture1.json fixture2.json fixture3.json` 做模型回归；该命令不能替代人工标注验收。

本地多文件剧本目录可用 `uv run python scripts/import_packages.py <目录> --save` 导入为草稿；作者真相与关键线索须校对。`scripts/complete_package.py` 可将 Git 忽略的本地校对配置应用于草稿；未确认授权的草稿即使 lint 通过也不能发布。

`uv run pytest` 运行测试（每个测试自建独立 schema，结束自动清理，需要可连的 `PG_DSN`）。对局事件和 LangGraph 节点快照写入 PostgreSQL，URL 中的 `game` 参数用于续局。搜证按线索成本扣点，地点容量和前置线索由代码校验；每幕可用点数和私聊次数由 fixture 决定。

P2 中，NPC 只接收角色认知视图；声明随事件追加。输出先做确定性泄密检查；配置 `LLM_MODEL` 时再经 LiteLLM 做语义判定。未配置模型的测试只能验证结构隔离与静态拦截，不能代表真实模型的泄密率。
V1 默认 `NPC_GENERATION_MODE=grounded`：模型选择授权证据 ID，代码呈现事实；`freeform` 仅用于对照实验，需接受更高的幻觉与拦截风险。

P3 可在复盘页按事件序号回放，并切换玩家或 NPC 视角。历史对话摘要按视角写入 PostgreSQL；当前默认 `CONTEXT_MODE=full`，`layered` 是超长局兜底，`auto` 可按字符近似预算自动切换。用 `uv run python scripts/compare_contexts.py` 比较同一局的两种上下文；配置模型后加 `--generate` 查看实际 token 与耗时。

P4 可在侧栏进入剧本库，上传 `.txt/.md/.docx/.pdf` 或完整 IR JSON。自然语言文件需要先配置模型；抽取失败和低置信度字段进入校对页。编辑 IR、解决校对项且质检无 blocker 后，才能发布并开局。

P5 公聊支持“面向全场”一次询问两位 NPC；导演只读取公开轨迹，安排 NPC 主动发言、公开线索反应及分级卡关提示。阶段和线索仍由代码裁定。

P6 用 `uv run python scripts/run_evals.py --output docs/V1_EVAL_REPORT.md` 运行四策略各 5 局离线评测；配置模型后加 `--live-model`。评测页可查看运行与案例。人工标注至少 20 组 `human,model` CSV 后，用 `uv run python scripts/calibrate_judge.py labels.csv` 检查 κ 是否达到 0.6。需要可共享的多幕回归样本时，使用完全合成的 `fixtures/multiact_demo.json`；本机素材指纹与复现说明见 `docs/LOCAL_CORPUS_MANIFEST.md`。

P7 已验证同局双席的私密事件隔离、`custom` 胜利条件、未知事件回放和记忆后端替换接口。这些是 V1 扩展钩子；实时多人房间不在 V1 范围。复盘使用逐项判分，上传剧本在开局前显示检测到的内容提示。

单机 API 可用 `uv run uvicorn jubensha.api.app:app --host 127.0.0.1 --port 8000` 启动，接口文档位于 `/docs`。需要从局域网开放 API 时先设置 `API_TOKEN`，客户端发送 `Authorization: Bearer <token>`。Streamlit 是 V1 的主要界面。

## 更换 fixture

设置 `SCRIPT_FIXTURE` 为另一个符合 `Script` schema 的 JSON 文件路径，启动前先用 `Script.model_validate_json` 校验。引擎不读取固定剧本 ID 或固定地点 ID。
