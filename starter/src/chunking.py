import re

from .models import Chunk, DocumentPage


def _make_chunk(page: DocumentPage, prefix: str, index: int, start: int, end: int) -> Chunk:
    meta = dict(page.metadata)
    meta.update(char_start=start, char_end=end)
    return Chunk(
        chunk_id=f"{page.document_id}:p{page.page}:{prefix}{index}",
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=page.text[start:end].strip(),
        metadata=meta,
    )


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("need size > 0 and 0 <= overlap < size")
    chunks, start, text = [], 0, page.text
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(_make_chunk(page, "f", len(chunks), start, end))
        if end == len(text):
            break
        start = end - overlap
    return chunks


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    boundary = re.compile(r"\n\s*\n|(?<=[.!?:;…])\n")
    spans, start = [], 0
    for match in boundary.finditer(text):
        if text[start:match.start()].strip():
            spans.append((start, match.start()))
        start = match.end()
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def _split_long(text: str, start: int, end: int, max_size: int) -> list[tuple[int, int]]:
    pieces = []
    sentence_ends = [start + m.end() for m in re.finditer(r"(?<=[.!?…])\s+", text[start:end])] + [end]
    cur, last = start, start
    for sent_end in sentence_ends:
        if sent_end - cur > max_size and last > cur:
            pieces.append((cur, last))
            cur = last
        last = sent_end
    pieces.append((cur, end))
    out = []
    for s, e in pieces:
        while e - s > max_size:
            out.append((s, s + max_size))
            s += max_size
        out.append((s, e))
    return out


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    spans: list[tuple[int, int]] = []
    for s, e in _paragraph_spans(page.text):
        spans.extend(_split_long(page.text, s, e, max_size) if e - s > max_size else [(s, e)])
    chunks, cur_start, cur_end = [], None, None
    for s, e in spans:
        if cur_start is not None and e - cur_start > max_size:
            chunks.append(_make_chunk(page, "p", len(chunks), cur_start, cur_end))
            cur_start = None
        if cur_start is None:
            cur_start = s
        cur_end = e
    if cur_start is not None:
        chunks.append(_make_chunk(page, "p", len(chunks), cur_start, cur_end))
    return chunks
