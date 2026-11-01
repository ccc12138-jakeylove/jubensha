# 评测报告：雾港谜案
- Run: de96e4dc932440d5b20a60d533e34b91
- 剧本：wugang_01
- 对局：20，完成：20
- 模型：ollama/qwen3.5:4b，temperature=0.3
- IR SHA256：3615635d9bba37c7ebc6b44c8bfcd0ba28010a78cc8dbf81fc8ff599c25a5eee

| 指标 | 结果 |
|---|---:|
| 完整通关率 | 70.0% |
| 正常策略通关率（不含元攻击） | 66.7% |
| 凶手指认率 | 70.0% |
| 二级卡关率 | 0.0% |
| 最终回复探针命中率 | 0.0% |
| 输出闸拦截率 | 17.1% |
| 平均回合数 | 16.8 |
| 不变量失败 | 0 |
| 输入/输出 token | 225819/12288 |
| p95 延迟 | 2746.0 ms |
| 成本 | 0.0 USD |
| 抽样 judge 均分 | 4.4625 |

探针数：41；工程门禁：失败；模型质量验收：待人工校准。

| 策略 | 局数 | 通关 | 主动发言不足两次 |
|---|---:|---:|---:|
| aggressive | 5 | 3 | 0 |
| passive | 5 | 4 | 0 |
| meta | 5 | 4 | 0 |
| speedrun | 5 | 3 | 0 |

## 限制
- Only one script and one act were exercised
- Judge scores are uncalibrated until paired human labels reach kappa >= 0.6
- Final probe hits use a separate lexical check, but semantic leakage still needs independent human review
