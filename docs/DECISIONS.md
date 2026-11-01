# P0 决策记录

## 已采用

- 附录 A 仅给出 `Secret.lie_script` 的 `act/probe/answer`；Schema 按示例保留这三个字段。
- P0 曾简化搜证；P1 改为玩家选搜查目标，按线索成本、地点容量、前置线索和每幕预算校验。目标名称在获得前可见，线索正文仍在搜得后显示。
- `GameState` 由 SQLite 事件流重放；P1 另加 LangGraph 节点 checkpoint，用于单回合图状态排查与恢复，不代替事件事实来源。
- 对局中 NPC 的事件视图仅含 `observable`，不包含真相动作或隐藏描述。

## 待确认

- SPEC 4.5 要求 `CONFRONT → VOTE`，而 P0 流程文字简写为 `SEARCH → VOTE`。本实现按正式转移表，在 UI 通过公聊进入指认。
- SPEC 4.3/5.2 的 `Secret` 使用 `Triple`、`LieTurn`，但 5.2 未定义两者字段；按附录 A 的三元组与 `act/probe/answer` 解析。
- 附录 A 把 E02 的投毒时间设为 t=-90（21:40），前言称实际死亡约 21:42；本实现不修订原始事实。
- 附录 A 省略地点、关系、泄密表和来源；P0 fixture 的补全内容需剧本作者核对。
- SPEC 第 12 章把完整阶段机列入 P1、三层隔离列入 P2；本轮任务明确要求两者的 P0 最小版，故以任务范围为准。
