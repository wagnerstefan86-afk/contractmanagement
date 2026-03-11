"""
Stage 2: Layout-aware chunking.

Entry point: chunk_structure_map(structure_map, contract_id) -> list[ChunkRecord]

Each StructureElement from Stage 1 is placed into a chunk that preserves its
layout_type. The chunker enforces these invariants:

  - HEADING elements always force a chunk boundary before emitting.
  - TABLE elements are always emitted as a single self-contained chunk;
    they are never merged with neighbouring paragraphs or split.
  - BULLET/NUMBERED groups: the preamble element (if any, identified by
    list_group_id) is merged with all items sharing that group_id into one
    chunk tagged 'bullet_list' or 'numbered_list'.
  - OCR_TEXT elements follow the same token-based splitting as paragraphs
    but carry layout_type='ocr_text' and propagate ocr_confidence.
  - Standard paragraphs use 400-token target / 512-token max with 50-token
    overlap carried forward between chunks.

Output rows are ready for bulk INSERT into contract_chunks.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Optional

import tiktoken

from pipeline.stages.stage1_ingestion import StructureElement

# ---------------------------------------------------------------------------
# Tokeniser (shared singleton — initialisation is expensive)
# ---------------------------------------------------------------------------

_ENCODER = tiktoken.get_encoding("cl100k_base")

TARGET_TOKENS  = 400
MAX_TOKENS     = 512
OVERLAP_TOKENS = 50


def _count(text: str) -> int:
    return len(_ENCODER.encode(text))


def _join(elements: list[StructureElement]) -> str:
    return "\n".join(e.text for e in elements)


# ---------------------------------------------------------------------------
# Output record
# ---------------------------------------------------------------------------

@dataclass
class ChunkRecord:
    contract_id: uuid.UUID
    chunk_index: int
    page_start: int
    page_end: int
    para_index_start: int
    para_index_end: int
    section_header: Optional[str]
    char_offset_start: int
    char_offset_end: int
    raw_text: str
    normalized_text: str
    token_count: int
    layout_type: str                      # layout_type_enum value
    ocr_confidence: Optional[float]       # only for ocr_text chunks
    table_data: Optional[dict]            # only for table chunks


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace. Punctuation preserved."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _dominant_layout(elements: list[StructureElement]) -> str:
    """Return the most common layout_type in a list of elements.

    For mixed chunks (paragraph + bullet), the non-paragraph type wins
    because it carries the most structural meaning for prompt selection.
    """
    counts: dict[str, int] = {}
    for e in elements:
        counts[e.layout_type] = counts.get(e.layout_type, 0) + 1
    # Priority override: if any element is ocr_text, the chunk is ocr_text
    if "ocr_text" in counts:
        return "ocr_text"
    return max(counts, key=counts.__getitem__)


def _avg_ocr_confidence(elements: list[StructureElement]) -> Optional[float]:
    confs = [e.ocr_confidence for e in elements if e.ocr_confidence is not None]
    return sum(confs) / len(confs) if confs else None


def _build_record(
    contract_id: uuid.UUID,
    chunk_index: int,
    elements: list[StructureElement],
    section_header: Optional[str],
    table_data: Optional[dict] = None,
) -> ChunkRecord:
    raw = _join(elements)
    tok = _count(raw)

    # Guard: hard truncate pathological chunks (single sentence > MAX_TOKENS)
    if tok > MAX_TOKENS:
        tokens = _ENCODER.encode(raw)
        raw = _ENCODER.decode(tokens[:MAX_TOKENS])
        tok = MAX_TOKENS

    layout = table_data and "table" or _dominant_layout(elements)
    ocr_conf = _avg_ocr_confidence(elements) if layout == "ocr_text" else None

    return ChunkRecord(
        contract_id=contract_id,
        chunk_index=chunk_index,
        page_start=min(e.page for e in elements),
        page_end=max(e.page for e in elements),
        para_index_start=min(e.para_index for e in elements),
        para_index_end=max(e.para_index for e in elements),
        section_header=section_header,
        char_offset_start=elements[0].char_offset_start,
        char_offset_end=elements[-1].char_offset_end,
        raw_text=raw,
        normalized_text=_normalize(raw),
        token_count=tok,
        layout_type=layout,
        ocr_confidence=ocr_conf,
        table_data=table_data,
    )


# ---------------------------------------------------------------------------
# Overlap buffer
# ---------------------------------------------------------------------------

def _compute_overlap(elements: list[StructureElement], target: int) -> list[StructureElement]:
    """Return the trailing elements whose combined token count reaches `target`.

    Iterates in reverse to preserve complete elements in the overlap window.
    """
    buf: list[StructureElement] = []
    accumulated = 0
    for elem in reversed(elements):
        tok = _count(elem.text)
        if accumulated + tok > target and buf:
            break
        buf.insert(0, elem)
        accumulated += tok
        if accumulated >= target:
            break
    return buf


# ---------------------------------------------------------------------------
# Sentence splitter (for oversized paragraphs)
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    try:
        import nltk
        return nltk.sent_tokenize(text)
    except Exception:
        # Fallback regex — less accurate for abbreviations
        return re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ\"])", text)


# ---------------------------------------------------------------------------
# Main chunker
# ---------------------------------------------------------------------------

def chunk_structure_map(
    structure_map: list[StructureElement],
    contract_id: uuid.UUID,
) -> list[ChunkRecord]:
    """Convert a Stage 1 structure map into chunk records for database insertion.

    Processing order:
      1. Group list elements (same list_group_id) into contiguous runs.
      2. Process each run/element through the token-budget algorithm.
    """
    chunks: list[ChunkRecord] = []
    chunk_index = 0
    current: list[StructureElement] = []        # active accumulator
    current_tokens = 0
    overlap_buf: list[StructureElement] = []    # carry-forward from previous chunk
    section_header: Optional[str] = None
    active_list_group: Optional[int] = None     # tracks current bullet group
    list_group_buf: list[StructureElement] = [] # accumulates entire list group

    def emit(elems: list[StructureElement], tdata: Optional[dict] = None) -> None:
        nonlocal chunk_index
        if not elems:
            return
        rec = _build_record(contract_id, chunk_index, elems, section_header, tdata)
        chunks.append(rec)
        chunk_index += 1

    def flush_current() -> list[StructureElement]:
        """Emit current accumulator and return overlap buffer for next chunk."""
        nonlocal current, current_tokens
        if current:
            emit(current)
            over = _compute_overlap(current, OVERLAP_TOKENS)
            current = []
            current_tokens = 0
            return over
        return []

    def add_to_current(elem: StructureElement) -> None:
        """Standard paragraph/OCR accumulation with token-budget splitting."""
        nonlocal current, current_tokens, overlap_buf, chunk_index

        elem_tok = _count(elem.text)

        if current_tokens + elem_tok <= TARGET_TOKENS:
            current.append(elem)
            current_tokens += elem_tok

        elif current_tokens + elem_tok <= MAX_TOKENS:
            # Accept slightly oversized to avoid splitting the element
            current.append(elem)
            current_tokens += elem_tok
            overlap_buf = flush_current()
            current = list(overlap_buf)
            current_tokens = _count(_join(current))

        else:
            # Element alone exceeds MAX_TOKENS — split at sentence boundaries
            sentences = _split_sentences(elem.text)
            for sentence in sentences:
                sent_tok = _count(sentence)
                if current_tokens + sent_tok > MAX_TOKENS:
                    overlap_buf = flush_current()
                    current = list(overlap_buf)
                    current_tokens = _count(_join(current))
                # Create a pseudo-element for the sentence
                sent_elem = StructureElement(
                    layout_type=elem.layout_type,
                    text=sentence,
                    page=elem.page,
                    para_index=elem.para_index,
                    char_offset_start=elem.char_offset_start,
                    char_offset_end=elem.char_offset_end,
                    ocr_confidence=elem.ocr_confidence,
                )
                current.append(sent_elem)
                current_tokens += sent_tok

    # ── Main loop ──
    for elem in structure_map:

        # ── HEADING: flush, update section_header, do NOT add to chunk ──
        if elem.layout_type == "heading":
            if list_group_buf:
                emit(list_group_buf)
                list_group_buf = []
                active_list_group = None
            overlap_buf = flush_current()
            section_header = elem.text
            # Heading itself seeds the overlap buffer for context continuity
            overlap_buf = [elem]
            current = [elem]
            current_tokens = _count(elem.text)
            continue

        # ── TABLE: always its own chunk, never merged ──
        if elem.layout_type == "table":
            if list_group_buf:
                emit(list_group_buf)
                list_group_buf = []
                active_list_group = None
            flush_current()
            overlap_buf = []
            current = []
            current_tokens = 0
            emit([elem], tdata=elem.table_data)
            continue

        # ── BULLET / NUMBERED LIST: accumulate by list_group_id ──
        if elem.layout_type in ("bullet_list", "numbered_list"):
            group_id = elem.list_group_id

            if group_id is not None and group_id == active_list_group:
                # Continue accumulating the current list group
                list_group_buf.append(elem)
            else:
                # New list group: flush the previous one
                if list_group_buf:
                    emit(list_group_buf)
                    list_group_buf = []
                # Flush any pending paragraph accumulator
                if current:
                    overlap_buf = flush_current()
                    current = list(overlap_buf)
                    current_tokens = _count(_join(current))
                active_list_group = group_id
                list_group_buf.append(elem)
            continue

        # ── PARAGRAPH / OCR_TEXT / preamble ──
        # A preamble paragraph belongs to the upcoming list group — buffer it.
        if elem.is_list_preamble:
            if list_group_buf:
                emit(list_group_buf)
                list_group_buf = []
                active_list_group = None
            # Preamble seeds the next list group's buffer
            list_group_buf.append(elem)
            continue

        # Close any open list group before processing a regular paragraph
        if list_group_buf:
            emit(list_group_buf)
            list_group_buf = []
            active_list_group = None

        # Seed current with carry-forward overlap if empty
        if not current and overlap_buf:
            current = list(overlap_buf)
            current_tokens = _count(_join(current))
            overlap_buf = []

        add_to_current(elem)

    # ── Flush remaining buffers ──
    if list_group_buf:
        emit(list_group_buf)
    if current:
        emit(current)

    return chunks
