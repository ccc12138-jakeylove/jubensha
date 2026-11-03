# 本机剧本素材清单

仓库只提交结构、哈希与复现入口，不提交剧本正文。同事拿到另行交付的
`_剧本/` 与 `local_reviews/` 后，先运行：

```bash
uv run python scripts/verify_local_corpus.py /path/to/_剧本 --compile
```

2026-11-03 本机素材的指纹如下（完整文件哈希见
`fixtures/local_corpus_manifest.json`）：

| 剧本 | script_id | 角色 | 幕 | 线索 | 草稿阻断项 |
|---|---|---:|---:|---:|---|
| 东方之星号游轮事件 | `package_cbee32a78c47` | 5 | 1 | 42 | 待补真相/关键证据 |
| 博物馆奇妙夜 | `package_7e890f8bec8c` | 6 | 1 | 82 | 待补真相/关键证据 |
| 大明星最后的演出 | `package_377bd2dbfe41` | 2 | 7 | 17 | 待补真相/关键证据 |
| 孝衣新娘 | `package_58adb415672d` | 10 | 1 | 45 | 待补真相/关键证据 |
| 怒海余生 | `package_19ecfed1dcf2` | 6 | 2 | 27 | 待补真相/关键证据 |

多幕本《怒海余生》《大明星最后的演出》的线索表没有幕分组，导入器现在
**保守归入第一幕**并产生 `MULTI_ACT_SCOPE_UNREVIEWED` 高优先级校对项；
作者必须在校对配置里设置 `act_clues` 后，草稿才可发布或试玩。

复现所需但未入库的材料：

1. 原始 `_剧本/MIRAGE_*` 目录（角色本、线索、GM 真相）；
2. `local_reviews/` 中的校对 JSON、评测 CSV/报告；
3. 若只需验证工程行为，可直接使用仓库内的合成双幕本
   `fixtures/multiact_demo.json`，不需要上述正文。
