# 评测报告：雾港谜案
- Run: b66ce9b3aa6d4c3f9967187a0c244c8b
- 剧本：wugang_01
- 对局：4，完成：4

| 指标 | 结果 |
|---|---:|
| 完整通关率 | 0.0% |
| 凶手指认率 | 100.0% |
| 二级卡关率 | 0.0% |
| 最终回复探针命中率 | 0.0% |
| 输出闸拦截率 | 36.6% |
| 平均回合数 | 14.8 |
| 不变量失败 | 0 |
| 输入/输出 token | 85507/5289 |
| p95 延迟 | 1452.0 ms |
| 成本 | 0.0 USD |
| 抽样 judge 均分 | 4.0 |

探针数：41；工程门禁：通过；模型质量验收：待人工校准。

## 限制
- Only one script and one act were exercised
- Judge scores are uncalibrated until paired human labels reach kappa >= 0.6
- Final probe hits use a separate lexical check, but semantic leakage still needs independent human review
