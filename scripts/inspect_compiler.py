import argparse
import json
import os
from pathlib import Path

from jubensha.compiler.ingest import read_document, segment_document
from jubensha.compiler.pipeline import _extract_field
from jubensha.llm.gateway import configured
from jubensha.storage.events import EventStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--fields", nargs="+", default=["characters", "clues", "truth_events"])
    args = parser.parse_args()
    if not configured():
        parser.error("LLM_MODEL is required")
    text = read_document(args.source.name.replace(".js", ".txt"), args.source.read_bytes())
    segments = segment_document(args.source.name, text)
    store = EventStore(os.getenv("GAME_DB", "compiler_inspect.db"))
    results = {}
    for field in args.fields:
        try:
            value, confidence, span, repaired = _extract_field(field, segments, store,
                                                                f"inspect:{args.source.stem}")
            results[field] = {"valid": True, "confidence": confidence, "source_span": span,
                              "items": len(value) if hasattr(value, "__len__") else 1,
                              "json_repaired": repaired}
        except Exception as exc:
            results[field] = {"valid": False, "error": str(exc)[:500]}
    print(json.dumps({"source": str(args.source), "segments": len(segments),
                      "fields": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
