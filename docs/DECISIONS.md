# P0 决策记录

## 已采用

- 附录 A 仅给出 `Secret.lie_script` 的 `act/probe/answer`；Schema 按示例保留这三个字段。
- P0 搜证按请求简化为地点首条未获得线索，不扣点数、不检查前置条件和容量。
- `GameState` 由 SQLite 事件流重放，暂不写 LangGraph checkpoint；页面刷新后继续使用事件流。
- 对局中 NPC 的事件视图仅含 `observable`，不包含真相动作或隐藏描述。

## 待确认

- SPEC 4.5 要求 `CONFRONT → VOTE`，而 P0 流程文字简写为 `SEARCH → VOTE`。本实现按正式转移表，在 UI 通过公聊进入指认。
- SPEC 4.3/5.2 的 `Secret` 使用 `Triple`、`LieTurn`，但 5.2 未定义两者字段；按附录 A 的三元组与 `act/probe/answer` 解析。
- 附录 A 把 E02 的投毒时间设为 t=-90（21:40），前言称实际死亡约 21:42；本实现不修订原始事实。
- 附录 A 省略地点、关系、泄密表和来源；P0 fixture 的补全内容需剧本作者核对。
- SPEC 第 12 章把完整阶段机列入 P1、三层隔离列入 P2；本轮任务明确要求两者的 P0 最小版，故以任务范围为准。
