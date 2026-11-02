import io
import re
from bisect import bisect_right
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pydantic import BaseModel, ConfigDict
from pypdf import PdfReader


class DocumentSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_doc: str
    title: str
    kind: str
    text: str
    source_span: tuple[int, int]
    page_number: int | None = None


def read_document(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in (".txt", ".md", ".json"):
        try:
            return content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return content.decode("gb18030")
    if suffix == ".docx":
        lines = []
        for block in Document(io.BytesIO(content)).iter_inner_content():
            if isinstance(block, Paragraph):
                prefix = "# " if block.style.name.startswith("Heading") else ""
                lines.append(prefix + block.text)
            elif isinstance(block, Table):
                lines.extend(" | ".join(cell.text for cell in row.cells) for row in block.rows)
        return "\n".join(lines)
    if suffix == ".pdf":
        return "\n".join(f"# Page {index}\n{page.extract_text(extraction_mode='layout') or ''}"
                         for index, page in enumerate(PdfReader(io.BytesIO(content)).pages, 1))
    raise ValueError(f"unsupported document type: {suffix}")


def segment_document(filename: str, text: str, max_chars: int = 4000) -> list[DocumentSegment]:
    page_starts = [match.start() for match in re.finditer(r"(?m)^# Page \d+\s*$", text)]
    headings = list(re.finditer(
        r"(?m)^(?:#{1,6}\s+|第[一二三四五六七八九十\d]+[幕章][^\n]*|(?:主持人手册|角色本|线索表|流程说明|时间线|人物关系)[:：][^\n]*)",
        text))
    starts = sorted({0, *(match.start() for match in headings), len(text)})
    segments = []
    for start, end in zip(starts, starts[1:]):
        block = text[start:end].strip()
        if not block:
            continue
        title = block.splitlines()[0][:100]
        kind = ("character" if "角色" in title else "clue" if "线索" in title
                else "truth" if "主持人" in title or "时间线" in title
                else "flow" if "幕" in title or "流程" in title else "general")
        for offset in range(0, len(block), max_chars):
            part = block[offset:offset + max_chars]
            page_number = bisect_right(page_starts, start + offset) if page_starts else None
            segments.append(DocumentSegment(source_doc=filename, title=title, kind=kind,
                                            text=part, source_span=(start + offset, start + offset + len(part)),
                                            page_number=page_number))
    return segments
