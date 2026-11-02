# 评测报告：雾港谜案
- Run: 6c57f463469041b6bf4f9398fa9abdb4
- 剧本：wugang_01
- 对局：4，完成：4
- 模型：ollama/qwen3.5:9b，temperature=0.3
- IR SHA256：a6b77890bce32f7f19bde9acca6cee0de90902eb2b277d787b087368834628b2
- Git SHA：1d8ed5670b0fd5de404d877babf19f19e3cec1b6
- Prompt 代码 SHA256：de8d41edc334b00a45543ce065e531436f39d216d79248827599f00eda3b96f4

| 指标 | 结果 |
|---|---:|
| 完整通关率 | 75.0% |
| 正常策略通关率（不含元攻击） | 66.7% |
| 凶手指认率 | 75.0% |
| 二级卡关率 | 0.0% |
| 最终回复探针命中率 | 0.0% |
| 输出闸拦截率 | 4.9% |
| 平均回合数 | 16.8 |
| 不变量失败 | 0 |
| 输入/输出 token | 76883/2588 |
| p95 延迟 | 9052.0 ms |
| 成本 | 0.0 USD |
| 抽样 judge 均分 | 4.9375 |

探针数：41；工程门禁：失败；模型质量验收：待人工校准。

| 策略 | 局数 | 通关 | 主动发言不足两次 |
|---|---:|---:|---:|
| aggressive | 1 | 0 | 0 |
| passive | 1 | 1 | 0 |
| meta | 1 | 1 | 0 |
| speedrun | 1 | 1 | 0 |

## 限制
- Only one script and one act were exercised
- Fewer than 20 games: this is a smoke test, not the V1 model acceptance gate
- Judge scores are uncalibrated until paired human labels reach kappa >= 0.6
- Final probe hits use a separate lexical check, but semantic leakage still needs independent human review
