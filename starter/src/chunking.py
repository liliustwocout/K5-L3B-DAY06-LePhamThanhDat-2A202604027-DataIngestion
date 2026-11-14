"""Fixed-size and paragraph-aware chunking strategies with metadata retention."""
from __future__ import annotations

import re
from typing import Any

from .models import Chunk, DocumentPage

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _make_chunk(
    page: DocumentPage, strategy_tag: str, index: int, text: str
) -> Chunk:
    """Create a Chunk with deterministic ID and copied page metadata."""
    meta: dict[str, Any] = dict(page.metadata)
    meta["chunk_index"] = index
    meta["chunk_char_len"] = len(text)
    return Chunk(
        chunk_id=f"{page.document_id}:p{page.page:03d}:{strategy_tag}:{index:03d}",
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=text,
        metadata=meta,
    )


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Split flattened page text into overlapping fixed-size character windows."""
    if size <= 0:
        raise ValueError(f"size must be > 0, got {size}")
    if overlap < 0 or overlap >= size:
        raise ValueError(f"overlap must satisfy 0 <= overlap < size, got {overlap} vs {size}")

    flat = re.sub(r"\s+", " ", page.text).strip()
    if not flat:
        return []

    chunks: list[Chunk] = []
    step = size - overlap
    start = 0
    idx = 0
    length = len(flat)

    while start < length:
        end = min(start + size, length)
        window = flat[start:end].strip()
        if window:
            chunks.append(_make_chunk(page, "fixed", idx, window))
            idx += 1
        if end >= length:
            break
        start += step

    return chunks


def _split_oversized_paragraph(paragraph: str, max_size: int) -> list[str]:
    """Split a paragraph larger than max_size on sentence boundaries, then hard-split if needed."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(paragraph) if s.strip()]
    if not sentences:
        return []

    parts: list[str] = []
    buf = ""

    for sent in sentences:
        if len(sent) > max_size:
            if buf:
                parts.append(buf)
                buf = ""
            for i in range(0, len(sent), max_size):
                piece = sent[i : i + max_size].strip()
                if piece:
                    parts.append(piece)
            continue

        candidate = f"{buf} {sent}".strip() if buf else sent
        if len(candidate) <= max_size:
            buf = candidate
        else:
            if buf:
                parts.append(buf)
            buf = sent

    if buf:
        parts.append(buf)
    return parts


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Group paragraphs up to max_size; split oversized paragraphs on sentence boundaries."""
    if max_size <= 0:
        raise ValueError(f"max_size must be > 0, got {max_size}")

    raw_paragraphs = [
        re.sub(r"\s+", " ", p).strip()
        for p in page.text.split("\n\n")
        if p.strip()
    ]
    if not raw_paragraphs:
        return []

    units: list[str] = []
    for para in raw_paragraphs:
        if len(para) <= max_size:
            units.append(para)
        else:
            units.extend(_split_oversized_paragraph(para, max_size))

    chunks: list[Chunk] = []
    buf = ""
    idx = 0

    for unit in units:
        candidate = f"{buf}\n\n{unit}".strip() if buf else unit
        if len(candidate) <= max_size:
            buf = candidate
        else:
            if buf:
                chunks.append(_make_chunk(page, "para", idx, buf))
                idx += 1
            buf = unit

    if buf:
        chunks.append(_make_chunk(page, "para", idx, buf))

    return chunks
