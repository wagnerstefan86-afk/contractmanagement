"""
Stage 1: Document Ingestion — layout-aware text extraction.

Entry point: parse_document(file_bytes) -> ParseResult

Returns a ParseResult containing an ordered list of StructureElements.
Each element is tagged with a layout_type that drives Stage 2 chunking
decisions and Stage 4 prompt selection.

Supported formats: PDF (via PyMuPDF), DOCX (via python-docx).
OCR fallback (Tesseract) activates per-page when extracted text < 50 chars.
"""

from __future__ import annotations

import hashlib
import re
import statistics
from dataclasses import dataclass, field
from typing import Optional

import fitz                     # PyMuPDF
import magic                    # python-magic
import nltk
import pytesseract
from docx import Document as DocxDocument
from PIL import Image

from pipeline.layout_detection import (
    detect_heading,
    detect_bullet,
    detect_numbered_list_item,
    is_list_preamble,
)

try:
    nltk.data.find("tokenizers/punkt")
except LookupError:
    nltk.download("punkt", quiet=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OCR_MIN_CHARS = 50
_OCR_CONFIDENCE_THRESHOLD = 0.70
_DOCX_WORDS_PER_PAGE = 500      # heuristic for DOCX page-break estimation

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StructureElement:
    layout_type: str            # matches layout_type_enum values
    text: str                   # raw text for this element
    page: int                   # 1-based page number
    para_index: int             # document-order index (for provenance)
    char_offset_start: int
    char_offset_end: int
    heading_level: Optional[int] = None    # 1-3 for headings
    table_data: Optional[dict] = None      # {"headers": [...], "rows": [[...]]}
    ocr_confidence: Optional[float] = None
    list_group_id: Optional[int] = None    # links bullet items to their preamble
    is_list_preamble: bool = False


@dataclass
class ParseResult:
    structure_map: list[StructureElement]
    page_count: int
    char_count: int
    heading_count: int
    ocr_pages: list[int]
    low_confidence_ocr_pages: list[int]   # ocr_confidence < _OCR_CONFIDENCE_THRESHOLD
    warnings: list[str]


# ---------------------------------------------------------------------------
# File type detection
# ---------------------------------------------------------------------------

def compute_sha256(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def detect_file_type(file_bytes: bytes) -> str:
    """Return 'pdf' or 'docx'. Raises ValueError for unsupported types.

    Uses python-magic for MIME detection; validates magic bytes as a second
    check to prevent extension-spoofing (e.g. a ZIP renamed to .pdf).
    """
    mime = magic.from_buffer(file_bytes[:2048], mime=True)

    if mime == "application/pdf" or file_bytes[:4] == b"%PDF":
        return "pdf"

    is_zip_mime = mime in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    )
    if is_zip_mime and file_bytes[:2] == b"PK":
        return "docx"

    raise ValueError(f"Unsupported file type: {mime}")


# ---------------------------------------------------------------------------
# OCR helpers
# ---------------------------------------------------------------------------

def _ocr_page(page: fitz.Page, dpi: int = 300) -> tuple[str, float]:
    """Rasterize a PDF page and run Tesseract OCR.

    Returns (reflowed_text, confidence_0_to_1).
    Confidence is the mean word-level confidence from Tesseract's TSV output.
    """
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    data = pytesseract.image_to_data(
        img,
        lang="deu+eng",
        config="--oem 3 --psm 6",
        output_type=pytesseract.Output.DICT,
    )

    words, confidences = [], []
    for i, conf in enumerate(data["conf"]):
        if conf == -1:          # Tesseract marks non-text blocks with -1
            continue
        word = data["text"][i].strip()
        if word:
            words.append(word)
            confidences.append(int(conf))

    raw_text = " ".join(words)
    avg_conf = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    return _reflow_ocr_text(raw_text), avg_conf


def _reflow_ocr_text(text: str) -> str:
    """Fix common OCR artefacts: soft hyphens, line-break hyphens, whitespace."""
    text = text.replace("\u00ad", "")                   # soft hyphen
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)        # "Vertrags-\npartner" → "Vertragspartner"
    text = re.sub(r"[ \t]{2,}", " ", text)              # collapse horizontal whitespace

    # Merge lines that do not end with sentence-terminal punctuation.
    lines = text.split("\n")
    buf: list[str] = []
    result: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            if buf:
                result.append(" ".join(buf))
                buf = []
            result.append("")
            continue
        buf.append(s)
        if s[-1] in ".!?:":
            result.append(" ".join(buf))
            buf = []
    if buf:
        result.append(" ".join(buf))

    return "\n".join(result)


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

def _median_font_size(page: fitz.Page) -> float:
    sizes: list[float] = []
    try:
        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    sz = span.get("size", 0)
                    if sz > 0:
                        sizes.append(sz)
    except Exception:
        pass
    return statistics.median(sizes) if sizes else 11.0


def _dominant_font_size(block: dict) -> Optional[float]:
    """Return the most common (by character count) font size in a text block."""
    size_chars: dict[float, int] = {}
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            sz = span.get("size", 0)
            if sz > 0:
                size_chars[sz] = size_chars.get(sz, 0) + len(span.get("text", ""))
    if not size_chars:
        return None
    return max(size_chars, key=size_chars.__getitem__)


def _rect_overlaps(block: dict, table_rects: list) -> bool:
    if not table_rects:
        return False
    block_rect = fitz.Rect(block[0], block[1], block[2], block[3])
    return any(block_rect.intersects(tr) for tr in table_rects)


def _parse_pdf_tables(page: fitz.Page, page_number: int, para_index: int, char_offset: int) -> tuple[list[StructureElement], list, int, int]:
    """Extract structured tables using PyMuPDF find_tables() (≥ 1.23).

    Returns (elements, table_rects, updated_para_index, updated_char_offset).
    table_rects is used downstream to skip text blocks that fall inside tables.
    """
    elements: list[StructureElement] = []
    table_rects = []

    try:
        tables = page.find_tables()
    except AttributeError:
        return elements, table_rects, para_index, char_offset

    for table in tables:
        bbox = table.bbox
        table_rect = fitz.Rect(bbox)
        table_rects.append(table_rect)

        extracted = table.extract() or []
        if not extracted:
            continue

        headers = [str(c or "").strip() for c in extracted[0]]
        rows = [[str(c or "").strip() for c in row] for row in extracted[1:]]

        # Pipe-delimited text for raw_text / embedding
        sep = " | "
        lines = []
        if headers:
            lines.append(sep.join(headers))
        for row in rows:
            lines.append(sep.join(row))
        table_text = "\n".join(lines).strip()

        if not table_text:
            continue

        elem = StructureElement(
            layout_type="table",
            text=table_text,
            page=page_number,
            para_index=para_index,
            char_offset_start=char_offset,
            char_offset_end=char_offset + len(table_text),
            table_data={"headers": headers, "rows": rows},
        )
        elements.append(elem)
        char_offset += len(table_text) + 1
        para_index += 1

    return elements, table_rects, para_index, char_offset


def parse_pdf(file_bytes: bytes) -> ParseResult:
    doc = fitz.open(stream=file_bytes, filetype="pdf")

    structure_map: list[StructureElement] = []
    ocr_pages: list[int] = []
    low_confidence_ocr_pages: list[int] = []
    warnings: list[str] = []
    heading_count = 0
    char_offset = 0
    para_index = 0
    list_group_counter = 0

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_number = page_num + 1
        median_fs = _median_font_size(page)

        # ── Tables first (removes their bounding rects from text block processing) ──
        table_elems, table_rects, para_index, char_offset = _parse_pdf_tables(
            page, page_number, para_index, char_offset
        )
        structure_map.extend(table_elems)

        # ── OCR check ──
        page_text_raw = page.get_text("text").strip()
        if len(page_text_raw) < _OCR_MIN_CHARS:
            ocr_pages.append(page_number)
            ocr_text, ocr_conf = _ocr_page(page)

            if ocr_conf < _OCR_CONFIDENCE_THRESHOLD:
                low_confidence_ocr_pages.append(page_number)
                warnings.append(
                    f"Page {page_number}: OCR confidence {ocr_conf:.0%} "
                    f"(threshold {_OCR_CONFIDENCE_THRESHOLD:.0%}) — human review recommended"
                )

            if ocr_text.strip():
                elem = StructureElement(
                    layout_type="ocr_text",
                    text=ocr_text,
                    page=page_number,
                    para_index=para_index,
                    char_offset_start=char_offset,
                    char_offset_end=char_offset + len(ocr_text),
                    ocr_confidence=ocr_conf,
                )
                structure_map.append(elem)
                char_offset += len(ocr_text) + 1
                para_index += 1
            continue

        # ── Normal text block extraction ──
        # Sort blocks top-to-bottom, left-to-right (10 px row buckets for columns)
        raw_blocks = page.get_text("blocks")
        raw_blocks.sort(key=lambda b: (round(b[1] / 10), b[0]))

        pending_preamble: Optional[StructureElement] = None

        for block in raw_blocks:
            if block[6] != 0:           # image block
                continue
            text = block[4].strip()
            if not text:
                continue
            if _rect_overlaps(block, table_rects):
                continue

            font_size = _dominant_font_size(
                # get_text("dict") is expensive; use cached median as fallback
                # Only call for blocks that might be headings (short text)
                page.get_text("dict") if len(text.split()) <= 20 else {}
            )

            heading_level = detect_heading(text, font_size, median_fs)

            if heading_level:
                layout = "heading"
                heading_count += 1
                pending_preamble = None
            elif detect_bullet(text):
                layout = "bullet_list"
            elif detect_numbered_list_item(text):
                # Short numbered items that match heading patterns were already
                # caught by detect_heading; reaching here means it's a list item.
                layout = "numbered_list"
            else:
                layout = "paragraph"

            elem = StructureElement(
                layout_type=layout,
                text=text,
                page=page_number,
                para_index=para_index,
                char_offset_start=char_offset,
                char_offset_end=char_offset + len(text),
                heading_level=heading_level,
                is_list_preamble=layout == "paragraph" and is_list_preamble(text),
            )

            # ── List group assignment ──
            if layout in ("bullet_list", "numbered_list"):
                if pending_preamble is not None:
                    if pending_preamble.list_group_id is None:
                        list_group_counter += 1
                        pending_preamble.list_group_id = list_group_counter
                    elem.list_group_id = pending_preamble.list_group_id
                else:
                    # Bullet without explicit preamble: continue previous group
                    # if the last element was also a list item, else start new.
                    last = structure_map[-1] if structure_map else None
                    if last and last.layout_type in ("bullet_list", "numbered_list"):
                        elem.list_group_id = last.list_group_id
                    else:
                        list_group_counter += 1
                        elem.list_group_id = list_group_counter
                pending_preamble = None
            elif elem.is_list_preamble:
                pending_preamble = elem
            else:
                pending_preamble = None

            structure_map.append(elem)
            char_offset += len(text) + 1
            para_index += 1

    return ParseResult(
        structure_map=structure_map,
        page_count=len(doc),
        char_count=char_offset,
        heading_count=heading_count,
        ocr_pages=ocr_pages,
        low_confidence_ocr_pages=low_confidence_ocr_pages,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# DOCX parsing
# ---------------------------------------------------------------------------

def _docx_heading_level(paragraph) -> Optional[int]:
    """Return heading level from paragraph style name, or None."""
    style_name = (paragraph.style.name or "").strip()
    if style_name.startswith("Heading"):
        # "Heading 1" → 1, "Heading 2" → 2, etc.
        m = re.search(r"\d+", style_name)
        if m:
            return min(int(m.group()), 3)
        return 1
    # German Word styles
    if style_name.startswith(("Überschrift", "Kapitel", "berschrift")):
        m = re.search(r"\d+", style_name)
        return min(int(m.group()), 3) if m else 1
    return None


def _estimate_docx_page(word_accumulator: int) -> int:
    return max(1, (word_accumulator // _DOCX_WORDS_PER_PAGE) + 1)


def parse_docx(file_bytes: bytes) -> ParseResult:
    import io
    doc = DocxDocument(io.BytesIO(file_bytes))

    structure_map: list[StructureElement] = []
    warnings: list[str] = []
    heading_count = 0
    char_offset = 0
    para_index = 0
    word_accumulator = 0
    list_group_counter = 0
    pending_preamble: Optional[StructureElement] = None

    def emit(elem: StructureElement) -> None:
        structure_map.append(elem)

    # ── Tables: extract before iterating paragraphs to preserve document order ──
    # python-docx does not provide document-order interleaving of paragraphs and
    # tables without iterating the raw XML. We iterate body children directly.
    from docx.oxml.ns import qn
    body = doc.element.body

    for child in body.iterchildren():
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "tbl":
            # Table element
            from docx.table import Table
            table = Table(child, doc)

            headers: list[str] = []
            rows: list[list[str]] = []
            for i, row in enumerate(table.rows):
                cells = [cell.text.strip() for cell in row.cells]
                if i == 0:
                    headers = cells
                else:
                    rows.append(cells)

            sep = " | "
            lines = []
            if headers:
                lines.append(sep.join(headers))
            for row in rows:
                lines.append(sep.join(row))
            table_text = "\n".join(lines).strip()

            if not table_text:
                continue

            page = _estimate_docx_page(word_accumulator)
            elem = StructureElement(
                layout_type="table",
                text=table_text,
                page=page,
                para_index=para_index,
                char_offset_start=char_offset,
                char_offset_end=char_offset + len(table_text),
                table_data={"headers": headers, "rows": rows},
            )
            emit(elem)
            char_offset += len(table_text) + 1
            para_index += 1
            pending_preamble = None

        elif tag == "p":
            from docx.text.paragraph import Paragraph
            para = Paragraph(child, doc)
            text = para.text.strip()
            if not text:
                continue

            word_accumulator += len(text.split())
            page = _estimate_docx_page(word_accumulator)

            heading_level = _docx_heading_level(para)

            # Check for list membership via paragraph XML
            is_list_para = (
                child.find(f".//{{{child.nsmap.get('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')}}}numPr") is not None
                if hasattr(child, "nsmap") else False
            )
            # Fallback: check by bullet characters or list-style names
            style_name = para.style.name or ""
            if not is_list_para:
                is_list_para = (
                    "List" in style_name
                    or "Aufzählung" in style_name
                    or detect_bullet(text)
                    or detect_numbered_list_item(text)
                )

            if heading_level:
                layout = "heading"
                heading_count += 1
                pending_preamble = None
            elif is_list_para or detect_bullet(text):
                layout = "bullet_list"
            elif detect_numbered_list_item(text):
                layout = "numbered_list"
            else:
                layout = "paragraph"

            elem = StructureElement(
                layout_type=layout,
                text=text,
                page=page,
                para_index=para_index,
                char_offset_start=char_offset,
                char_offset_end=char_offset + len(text),
                heading_level=heading_level,
                is_list_preamble=layout == "paragraph" and is_list_preamble(text),
            )

            # List group assignment (same logic as PDF parser)
            if layout in ("bullet_list", "numbered_list"):
                if pending_preamble is not None:
                    if pending_preamble.list_group_id is None:
                        list_group_counter += 1
                        pending_preamble.list_group_id = list_group_counter
                    elem.list_group_id = pending_preamble.list_group_id
                else:
                    last = structure_map[-1] if structure_map else None
                    if last and last.layout_type in ("bullet_list", "numbered_list"):
                        elem.list_group_id = last.list_group_id
                    else:
                        list_group_counter += 1
                        elem.list_group_id = list_group_counter
                pending_preamble = None
            elif elem.is_list_preamble:
                pending_preamble = elem
            else:
                pending_preamble = None

            emit(elem)
            char_offset += len(text) + 1
            para_index += 1

    estimated_pages = max(1, _estimate_docx_page(word_accumulator))
    if estimated_pages > 1:
        warnings.append(
            f"DOCX page count is estimated ({estimated_pages} pages at "
            f"{_DOCX_WORDS_PER_PAGE} words/page). Page numbers in chunks are approximate."
        )

    return ParseResult(
        structure_map=structure_map,
        page_count=estimated_pages,
        char_count=char_offset,
        heading_count=heading_count,
        ocr_pages=[],
        low_confidence_ocr_pages=[],
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def parse_document(file_bytes: bytes) -> ParseResult:
    file_type = detect_file_type(file_bytes)
    if file_type == "pdf":
        return parse_pdf(file_bytes)
    if file_type == "docx":
        return parse_docx(file_bytes)
    raise ValueError(f"Unhandled file type: {file_type}")
