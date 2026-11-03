# 测试夹具

- `wugang_01.json`：V1 内置固定本，覆盖单幕、私密线索、秘密与多席位。
- `multiact_demo.json`：**完全合成的双幕可共享测试本**，用于复现多幕隔离、
  动机裁判与模拟玩家回归。不含任何外部剧本正文，可直接随仓库分发。
  运行：`uv run python scripts/run_evals.py --fixture fixtures/multiact_demo.json --games-per-persona 1`
- `local_corpus_manifest.json`：用户提供的五本本机素材的结构与 SHA256 清单，
  **不含正文**。正文与 `local_reviews/` 仍需另行交付，见
  [本机素材清单](../docs/LOCAL_CORPUS_MANIFEST.md)。

`multiact_demo.json` 的关键设计：第一幕线索只揭示第一幕事件，第二幕线索
需要前置线索才能取得；林岚的分幕目标在第二幕才进入角色视角。可用于验证
“多幕本不会在开局泄露后续目标/线索”。
