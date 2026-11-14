"""Read and normalize source PDFs with page-level traceability."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .models import DocumentPage

_HEADING_OR_ITEM_RE = re.compile(
    r"^(?:"
    r"\d+(?:\.\d+)*\.?\s+[A-Z]"
    r"|Appendix\s+[A-Z]\b"
    r"|[•●▪◦]\s+"
    r"|o\s+[“\"A-Z]"
    r"|(?:PO|PS|PW|RV)\.\d+(?:\.\d+)?[:\s]"
    r"|[RCN]\d+:\s"
    r"|Fig\.\s*\d+"
    r"|Table\s+\d+"
    r")"
)


def _is_short_heading(line: str) -> bool:
    """Return True for standalone short subheadings without sentence-ending punctuation."""
    if len(line) > 58 or len(line) < 3:
        return False
    if line[-1] in ".,;?!":
        return False
    return line[0].isupper() and not line.endswith("-")


def normalize_text(text: str) -> str:
    """Normalize Unicode/whitespace while reconstructing PDF paragraph boundaries."""
    normalized = unicodedata.normalize("NFKC", text or "")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in normalized.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""

    long_lengths = sorted(len(ln) for ln in lines if len(ln) >= 35)
    p75_len = long_lengths[int(0.75 * (len(long_lengths) - 1))] if long_lengths else 72
    wrap_threshold = max(58, int(p75_len * 0.86))

    paragraphs: list[list[str]] = [[lines[0]]]
    for prev, curr in zip(lines, lines[1:]):
        first_word = curr.split(" ", 1)[0]
        prev_ended_sentence = prev.endswith((".", "?", "!", ":", '."', ".”"))
        short_prev_end = prev_ended_sentence and (len(prev) + 1 + len(first_word) < wrap_threshold)
        starts_new_block = bool(_HEADING_OR_ITEM_RE.match(curr)) or _is_short_heading(curr)

        if starts_new_block or short_prev_end:
            paragraphs.append([curr])
        else:
            paragraphs[-1].append(curr)

    return "\n\n".join(" ".join(p) for p in paragraphs)


def _detect_section(text: str, previous_section: str) -> str:
    """Extract the first numbered/top heading on the page or carry forward the previous one."""
    for para in text.split("\n\n"):
        first_line = para.split("\n", 1)[0].strip()
        m = re.match(r"^(\d+(?:\.\d+)*\.?\s+[A-Z][^\n.;:]{2,70})", first_line)
        if m:
            return m.group(1).strip()
        if _is_short_heading(first_line) and not first_line.startswith(("NIST ", "July ", "March ")):
            return first_line
    return previous_section


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Extract each 1-based physical page, preserving page number, source, and error flags."""
    if not path.exists():
        raise FileNotFoundError(f"PDF source file not found: {path}")

    reader = PdfReader(str(path))
    pages: list[DocumentPage] = []
    current_section = "front_matter"

    for page_num, raw_page in enumerate(reader.pages, start=1):
        try:
            raw_text = raw_page.extract_text() or ""
            extract_error = None
        except Exception as exc:  # pragma: no cover - defensive PDF error capture
            raw_text = ""
            extract_error = f"{type(exc).__name__}: {exc}"

        clean_text = normalize_text(raw_text)
        current_section = _detect_section(clean_text, current_section)
        char_count = len(re.sub(r"\s+", " ", clean_text).strip())
        is_empty = char_count == 0

        pages.append(
            DocumentPage(
                document_id=document_id,
                source=source,
                page=page_num,
                text=clean_text,
                metadata={
                    "section": current_section,
                    "char_count": char_count,
                    "is_empty": is_empty,
                    "extract_error": extract_error,
                },
            )
        )
    return pages


def load_corpus_from_manifest(
    manifest_path: Path, root_dir: Path
) -> tuple[list[DocumentPage], dict[str, Any]]:
    """Load valid content pages defined in data/manifest.json and collect ingestion telemetry."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    valid_pages: list[DocumentPage] = []
    doc_logs: list[dict[str, Any]] = []

    for doc_info in manifest["documents"]:
        doc_id = doc_info["source_id"]
        rel_path = doc_info["local_path"]
        pdf_path = root_dir / rel_path
        all_pages = load_pdf(pdf_path, document_id=doc_id, source=rel_path)

        valid_set = set(doc_info["valid_page_numbers"])
        empty_pages = [p.page for p in all_pages if p.metadata.get("is_empty")]
        error_pages = [
            {"page": p.page, "error": p.metadata.get("extract_error")}
            for p in all_pages
            if p.metadata.get("extract_error")
        ]

        doc_valid_count = 0
        doc_valid_chars = 0
        for p in all_pages:
            if p.page not in valid_set:
                continue
            p.metadata.update(
                {
                    "title": doc_info["title"],
                    "year": int(doc_info["year"]),
                    "category": str(doc_info["category"]),
                    "license": doc_info["license_or_permission"],
                }
            )
            valid_pages.append(p)
            doc_valid_count += 1
            doc_valid_chars += int(p.metadata["char_count"])

        doc_logs.append(
            {
                "document_id": doc_id,
                "local_path": rel_path,
                "physical_pages": len(all_pages),
                "valid_content_pages": doc_valid_count,
                "excluded_pages_count": len(all_pages) - doc_valid_count,
                "empty_pages": empty_pages,
                "error_pages": error_pages,
                "valid_normalized_chars": doc_valid_chars,
                "year": int(doc_info["year"]),
                "category": str(doc_info["category"]),
            }
        )

    ingestion_log = {
        "manifest_path": str(manifest_path.relative_to(root_dir)),
        "total_documents": len(doc_logs),
        "total_physical_pages": sum(d["physical_pages"] for d in doc_logs),
        "total_valid_content_pages": len(valid_pages),
        "total_valid_normalized_chars": sum(d["valid_normalized_chars"] for d in doc_logs),
        "documents": doc_logs,
    }
    return valid_pages, ingestion_log
