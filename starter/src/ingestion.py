import logging
import re
import unicodedata
from pathlib import Path

from pypdf import PdfReader

from .models import DocumentPage

_INVISIBLE = dict.fromkeys(map(ord, "­​‌‍⁠﻿"), None)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = re.sub(r"([a-z]) ?-\n([a-z])", r"\1\2", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_pdf(path: Path, document_id: str, source: str, metadata: dict | None = None,
             header_regex: str | None = None) -> tuple[list[DocumentPage], list[dict]]:
    pages: list[DocumentPage] = []
    log: list[dict] = []
    header = re.compile(header_regex) if header_regex else None
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(str(path))
    for number, pdf_page in enumerate(reader.pages, start=1):
        try:
            raw = pdf_page.extract_text() or ""
        except Exception as exc:
            log.append({"document_id": document_id, "page": number, "status": "error", "detail": repr(exc)})
            continue
        text = normalize_text(raw)
        if header:
            first, _, rest = text.partition("\n")
            if header.fullmatch(first):
                text = rest.strip()
        if not text:
            log.append({"document_id": document_id, "page": number, "status": "empty", "detail": "no extractable text"})
            continue
        pages.append(DocumentPage(document_id, source, number, text, dict(metadata or {})))
    return pages, log
