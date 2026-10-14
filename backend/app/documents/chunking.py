"""Structure-aware chunking: never crosses a page or section boundary, keeps char offsets."""

from __future__ import annotations

from dataclasses import dataclass

from app.documents.parsers import Block


@dataclass
class ChunkSpec:
    text: str
    page: int | None
    section: str | None
    char_start: int
    char_end: int


def chunk_blocks(blocks: list[Block], *, target_chars: int = 900, overlap_chars: int = 120) -> list[ChunkSpec]:
    chunks: list[ChunkSpec] = []
    buf: list[str] = []
    buf_start = 0
    cur_page: int | None = None
    cur_section: str | None = None
    offset = 0

    def flush() -> None:
        nonlocal buf, buf_start
        if buf:
            text = "\n\n".join(buf)
            chunks.append(ChunkSpec(text, cur_page, cur_section, buf_start, buf_start + len(text)))
        buf = []

    for b in blocks:
        if b.page != cur_page or b.section != cur_section or b.kind == "heading":
            flush()
            cur_page, cur_section = b.page, b.section
            buf_start = offset
        pieces = _split_long(b.text, target_chars, overlap_chars)
        for piece in pieces:
            if buf and sum(len(x) for x in buf) + len(piece) > target_chars:
                flush()
                buf_start = offset
            if not buf:
                buf_start = offset
            buf.append(piece)
        offset += len(b.text) + 2
    flush()
    return [c for c in chunks if c.text.strip()]


def _split_long(text: str, target: int, overlap: int) -> list[str]:
    if len(text) <= target:
        return [text]
    out, i = [], 0
    while i < len(text):
        end = min(len(text), i + target)
        if end < len(text):
            cut = text.rfind(". ", i, end)
            if cut > i + target // 2:
                end = cut + 1
        out.append(text[i:end].strip())
        if end >= len(text):
            break
        i = max(end - overlap, i + 1)
    return out


def chunk_plain(text: str, *, target_chars: int = 900) -> list[ChunkSpec]:
    return chunk_blocks([Block(p) for p in text.split("\n\n") if p.strip()] or [Block(text)], target_chars=target_chars)
