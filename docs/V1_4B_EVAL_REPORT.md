# 评测报告：雾港谜案
- Run: aeeafb82b56e44e28f5e47c1d2a8ddc4
- 剧本：wugang_01
- 对局：4，完成：4

| 指标 | 结果 |
|---|---:|
| 完整通关率 | 75.0% |
| 凶手指认率 | 75.0% |
| 二级卡关率 | 0.0% |
| 最终回复探针命中率 | 0.0% |
| 输出闸拦截率 | 46.3% |
| 平均回合数 | 15.0 |
| 不变量失败 | 0 |
| 输入/输出 token | 104055/8362 |
| p95 延迟 | 1972.0 ms |
| 成本 | 0.0 USD |
| 抽样 judge 均分 | 4.1875 |

探针数：41；工程门禁：通过；模型质量验收：待人工校准。

## 限制
- Only one script and one act were exercised
- Judge scores are uncalibrated until paired human labels reach kappa >= 0.6
- Final probe hits use a separate lexical check, but semantic leakage still needs independent human review
