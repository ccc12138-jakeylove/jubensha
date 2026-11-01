# 评测报告：雾港谜案
- Run: e13674749b934cf088b2b165b2a09766
- 剧本：wugang_01
- 对局：4，完成：4

| 指标 | 结果 |
|---|---:|
| 完整通关率 | 0.0% |
| 凶手指认率 | 25.0% |
| 二级卡关率 | 0.0% |
| 原始候选风险命中率 | 41.5% |
| 平均回合数 | 13.5 |
| 不变量失败 | 0 |
| 输入/输出 token | 50403/3316 |
| p95 延迟 | 1420.0 ms |
| 成本 | 0.0 USD |
| 抽样 judge 均分 | 4.0625 |

探针数：41；工程门禁：失败；模型质量验收：待人工校准。

## 限制
- Only one script and one act were exercised
- Judge scores are uncalibrated until paired human labels reach kappa >= 0.6
- Probe risk rate is measured on raw NPC candidates and may contain detector false positives; post-guard leakage needs independent review
