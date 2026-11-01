# 评测报告：雾港谜案
- Run: 5c7579e7093640eb8c7699c711fe1448
- 剧本：wugang_01
- 对局：20，完成：20

| 指标 | 结果 |
|---|---:|
| 完整通关率 | 75.0% |
| 正常策略通关率（不含元攻击） | 66.7% |
| 凶手指认率 | 85.0% |
| 二级卡关率 | 0.0% |
| 最终回复探针命中率 | 0.0% |
| 输出闸拦截率 | 56.1% |
| 平均回合数 | 16.8 |
| 不变量失败 | 0 |
| 输入/输出 token | 364675/28830 |
| p95 延迟 | 2434.0 ms |
| 成本 | 0.0 USD |
| 抽样 judge 均分 | 4.6 |

探针数：41；工程门禁：失败；模型质量验收：待人工校准。

| 策略 | 局数 | 通关 | 主动发言不足两次 |
|---|---:|---:|---:|
| aggressive | 5 | 2 | 0 |
| passive | 5 | 4 | 0 |
| meta | 5 | 5 | 0 |
| speedrun | 5 | 4 | 0 |

## 限制
- Only one script and one act were exercised
- Judge scores are uncalibrated until paired human labels reach kappa >= 0.6
- Final probe hits use a separate lexical check, but semantic leakage still needs independent human review
