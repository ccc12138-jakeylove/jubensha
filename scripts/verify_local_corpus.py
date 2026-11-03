"""校验本机剧本素材与 fixtures/local_corpus_manifest.json 是否一致。

仓库不提交剧本正文；同事拿到另行交付的 `_剧本` 目录后，可用本脚本确认
文件版本与生成草稿时一致，再配合 local_reviews/ 复现校对结果。
"""

import argparse
import hashlib
import json
from pathlib import Path

from jubensha.compiler.package import compile_package


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path, help="包含 MIRAGE_* 目录的 _剧本 根目录")
    parser.add_argument("--manifest", type=Path,
                        default=Path("fixtures/local_corpus_manifest.json"))
    parser.add_argument("--compile", action="store_true",
                        help="同时重新编译，核对 script_id 与角色/幕/线索数量")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    problems = []
    for item in manifest["scripts"]:
        folder = args.corpus / f"MIRAGE_{item['title']}"
        if not folder.is_dir():
            problems.append(f"缺少目录 {folder}")
            continue
        for record in item["files"]:
            path = args.corpus / record["path"]
            if not path.is_file():
                problems.append(f"缺少文件 {record['path']}")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != record["sha256"]:
                problems.append(f"哈希不一致 {record['path']}")
        if args.compile:
            draft = compile_package(folder)
            actual = {"script_id": draft.ir["script_id"],
                      "roles": len(draft.ir["characters"]),
                      "acts": len(draft.ir["acts"]),
                      "clues": len(draft.ir["clues"])}
            for key, value in actual.items():
                if value != item[key]:
                    problems.append(f"{item['title']} {key}: {value} != {item[key]}")
        print(f"{item['title']}: {item['script_id']} 已核对")
    if problems:
        print("\n".join(problems))
        return 1
    print("全部素材与清单一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
