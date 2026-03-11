"""
Stage 4: Layout-aware clause extraction.

Entry point: build_extraction_messages(chunk) -> tuple[str, str]
  Returns (system_prompt, user_message) ready for the Haiku API call.

Each layout type gets a distinct prompt variant that accounts for the
structural properties of that content type:

  paragraph    — standard clause extraction; one or more clauses per chunk
  bullet_list  — preamble + items form one obligation; extract each item
                 as a clause but prepend the preamble subject for context
  numbered_list — same as bullet_list
  table        — each row with an obligation verb is a separate clause;
                 column headers provide the obligation subject
  heading      — headings rarely contain operative content; prompt is minimal
  ocr_text     — identical to paragraph but warns the model about OCR errors
                 and enables liberal spelling interpretation

The JSON schema returned by all variants is identical so downstream
processing (Stage 4 merge and DB insert) is layout-agnostic.
"""

from __future__ import annotations

import json
from typing import Optional

# ---------------------------------------------------------------------------
# Shared system prompt base
# ---------------------------------------------------------------------------

_SYSTEM_BASE = """\
You are a contract clause extraction specialist. Extract discrete contractual \
clauses from the provided contract text chunk. A clause is a self-contained \
contractual obligation, right, or condition.

Do NOT extract:
- Pure definitions (unless the definition itself contains an obligation)
- Table of contents entries, page headers, footers
- Signature blocks
- Generic boilerplate with no operative legal effect

Extract verbatim clause text. Do not paraphrase.
Return ONLY valid JSON matching the schema below — no additional text.\
"""

# ---------------------------------------------------------------------------
# JSON schema documentation (embedded in every user message)
# ---------------------------------------------------------------------------

_RESPONSE_SCHEMA = """\
{
  "clauses": [
    {
      "clause_text": "<verbatim text of the clause>",
      "section_reference": "<section number or heading, e.g. '12.3' or 'Schedule 2', or null>",
      "starts_at_char": <integer — 0-indexed char offset within the chunk text>,
      "ends_at_char": <integer — exclusive end offset>,
      "is_continuation": <boolean — true if clause continues from previous chunk>,
      "is_truncated": <boolean — true if clause continues into next chunk>,
      "extraction_notes": "<optional: uncertainty or structural note, or empty string>"
    }
  ],
  "chunk_has_operative_content": <boolean>,
  "skipped_reason": "<if chunk_has_operative_content is false, brief reason, else empty string>"
}\
"""

# ---------------------------------------------------------------------------
# Layout-specific system prompt additions
# ---------------------------------------------------------------------------

_PARAGRAPH_ADDITION = ""  # no addition needed

_BULLET_LIST_ADDITION = """

IMPORTANT — BULLET LIST HANDLING:
This chunk contains a bullet or numbered list. The chunk may begin with a
preamble sentence that introduces the list (e.g. "The Supplier shall:").
Apply these rules:
- If a preamble sentence precedes the list items, prepend it to each item's
  clause_text to form a complete, self-contained obligation.
- Extract each bullet item as a separate clause object.
- Do not extract the preamble as a standalone clause.
- If a bullet item is itself a sub-list (indented), include it within its
  parent item's clause_text.\
"""

_TABLE_ADDITION = """

IMPORTANT — TABLE HANDLING:
This chunk contains tabular data presented as pipe-delimited rows.
The first row contains column headers; subsequent rows contain values.
Apply these rules:
- Interpret each data row as a potential obligation. Extract a clause only
  if the row, combined with its column headers, expresses a contractual
  obligation (look for obligation verbs: shall, must, will, is required to).
- Construct the clause_text as a readable sentence: combine the header
  label with the cell value (e.g. "Response Time: 4 hours" → "The Supplier
  shall respond within 4 hours."). Preserve verbatim cell text.
- Do not extract header-only rows or rows that contain only metadata
  (e.g. document version, effective date).
- set section_reference to the table caption or the nearest section heading
  visible in the chunk.\
"""

_OCR_ADDITION = """

IMPORTANT — OCR TEXT HANDLING:
This text was extracted via optical character recognition (OCR) from a scanned
document and may contain recognition errors (e.g. "shaii" instead of "shall",
"§" recognised as "S", split words from hyphenation, extra whitespace).
Apply these rules:
- Correct obvious OCR errors when extracting clause_text; note corrections
  in extraction_notes.
- If a word is ambiguous, preserve the OCR output verbatim and flag it in
  extraction_notes.
- Apply liberal matching when determining whether text contains an obligation
  verb (e.g. "shaii" → "shall", "wiil" → "will").\
"""

_HEADING_ADDITION = """

NOTE: This chunk consists of or is dominated by a section heading.
Headings rarely contain operative content. Extract a clause only if the
heading text itself states an explicit obligation or right.\
"""

# ---------------------------------------------------------------------------
# Per-layout-type prompt builders
# ---------------------------------------------------------------------------

def _system_prompt(addition: str) -> str:
    return _SYSTEM_BASE + addition


def _user_message_paragraph(chunk_text: str, section_header: Optional[str], chunk_index: int, total_chunks: int) -> str:
    ctx = section_header or "Unknown Section"
    return (
        f"Extract all contractual clauses from the following contract text chunk.\n\n"
        f"SECTION CONTEXT: {ctx}\n"
        f"CHUNK POSITION: Chunk {chunk_index} of {total_chunks}\n\n"
        f"CONTRACT TEXT:\n---\n{chunk_text}\n---\n\n"
        f"Return JSON matching this schema:\n{_RESPONSE_SCHEMA}"
    )


def _user_message_bullet(
    chunk_text: str,
    section_header: Optional[str],
    chunk_index: int,
    total_chunks: int,
) -> str:
    ctx = section_header or "Unknown Section"
    return (
        f"Extract contractual clauses from the following bullet/numbered list chunk.\n\n"
        f"SECTION CONTEXT: {ctx}\n"
        f"CHUNK POSITION: Chunk {chunk_index} of {total_chunks}\n\n"
        f"LIST TEXT:\n---\n{chunk_text}\n---\n\n"
        f"Remember: prepend the preamble sentence to each bullet item's clause_text "
        f"to form a complete obligation. Extract each bullet item as a separate clause.\n\n"
        f"Return JSON matching this schema:\n{_RESPONSE_SCHEMA}"
    )


def _user_message_table(
    chunk_text: str,
    table_data: Optional[dict],
    section_header: Optional[str],
    chunk_index: int,
    total_chunks: int,
) -> str:
    ctx = section_header or "Unknown Section"

    # Provide structured table data if available (more reliable than pipe text)
    if table_data and table_data.get("headers") and table_data.get("rows"):
        headers = table_data["headers"]
        rows = table_data["rows"]
        table_repr = "Headers: " + " | ".join(headers) + "\n"
        for i, row in enumerate(rows, 1):
            table_repr += f"Row {i}: " + " | ".join(
                f"{h}={v}" for h, v in zip(headers, row)
            ) + "\n"
    else:
        table_repr = chunk_text

    return (
        f"Extract contractual clauses from the following table.\n\n"
        f"SECTION CONTEXT: {ctx}\n"
        f"CHUNK POSITION: Chunk {chunk_index} of {total_chunks}\n\n"
        f"TABLE DATA:\n---\n{table_repr}---\n\n"
        f"RAW TEXT (pipe-delimited fallback):\n---\n{chunk_text}\n---\n\n"
        f"Extract only rows that express a contractual obligation. "
        f"Combine column header with cell value to form a readable clause_text sentence.\n\n"
        f"Return JSON matching this schema:\n{_RESPONSE_SCHEMA}"
    )


def _user_message_ocr(
    chunk_text: str,
    section_header: Optional[str],
    chunk_index: int,
    total_chunks: int,
    ocr_confidence: Optional[float],
) -> str:
    ctx = section_header or "Unknown Section"
    conf_note = (
        f"OCR confidence for this page: {ocr_confidence:.0%}. "
        f"{'Low confidence — expect more errors.' if ocr_confidence is not None and ocr_confidence < 0.70 else 'Confidence acceptable.'}"
        if ocr_confidence is not None else "OCR confidence: unknown."
    )
    return (
        f"Extract contractual clauses from the following OCR-extracted contract text.\n\n"
        f"SECTION CONTEXT: {ctx}\n"
        f"CHUNK POSITION: Chunk {chunk_index} of {total_chunks}\n"
        f"{conf_note}\n\n"
        f"CONTRACT TEXT (may contain OCR errors):\n---\n{chunk_text}\n---\n\n"
        f"Correct clear OCR errors in clause_text. Note corrections in extraction_notes. "
        f"Treat 'shaii'/'musl'/'wiil' as 'shall'/'must'/'will'.\n\n"
        f"Return JSON matching this schema:\n{_RESPONSE_SCHEMA}"
    )


def _user_message_heading(
    chunk_text: str,
    section_header: Optional[str],
    chunk_index: int,
    total_chunks: int,
) -> str:
    ctx = section_header or "Unknown Section"
    return (
        f"Assess whether the following section heading contains any operative "
        f"contractual content worth extracting as a clause.\n\n"
        f"SECTION CONTEXT: {ctx}\n"
        f"CHUNK POSITION: Chunk {chunk_index} of {total_chunks}\n\n"
        f"HEADING TEXT:\n---\n{chunk_text}\n---\n\n"
        f"Most headings have no operative content — return chunk_has_operative_content: false "
        f"unless the heading itself states an explicit obligation or right.\n\n"
        f"Return JSON matching this schema:\n{_RESPONSE_SCHEMA}"
    )


# ---------------------------------------------------------------------------
# Dispatch function
# ---------------------------------------------------------------------------

def build_extraction_messages(
    chunk_raw_text: str,
    chunk_layout_type: str,
    chunk_section_header: Optional[str],
    chunk_index: int,
    total_chunks: int,
    chunk_table_data: Optional[dict] = None,
    chunk_ocr_confidence: Optional[float] = None,
) -> tuple[str, str]:
    """Return (system_prompt, user_message) for the Haiku clause extraction call.

    Args:
        chunk_raw_text:       ContractChunk.raw_text
        chunk_layout_type:    ContractChunk.layout_type (layout_type_enum value)
        chunk_section_header: ContractChunk.section_header
        chunk_index:          ContractChunk.chunk_index
        total_chunks:         total number of chunks for this contract
        chunk_table_data:     ContractChunk.table_data (non-None for table chunks)
        chunk_ocr_confidence: ContractChunk.ocr_confidence (non-None for ocr_text chunks)
    """
    layout = chunk_layout_type

    if layout == "table":
        system = _system_prompt(_TABLE_ADDITION)
        user = _user_message_table(
            chunk_raw_text,
            chunk_table_data,
            chunk_section_header,
            chunk_index,
            total_chunks,
        )

    elif layout in ("bullet_list", "numbered_list"):
        system = _system_prompt(_BULLET_LIST_ADDITION)
        user = _user_message_bullet(
            chunk_raw_text,
            chunk_section_header,
            chunk_index,
            total_chunks,
        )

    elif layout == "ocr_text":
        system = _system_prompt(_OCR_ADDITION)
        user = _user_message_ocr(
            chunk_raw_text,
            chunk_section_header,
            chunk_index,
            total_chunks,
            chunk_ocr_confidence,
        )

    elif layout == "heading":
        system = _system_prompt(_HEADING_ADDITION)
        user = _user_message_heading(
            chunk_raw_text,
            chunk_section_header,
            chunk_index,
            total_chunks,
        )

    else:
        # 'paragraph' and any future unrecognised types → standard extraction
        system = _system_prompt(_PARAGRAPH_ADDITION)
        user = _user_message_paragraph(
            chunk_raw_text,
            chunk_section_header,
            chunk_index,
            total_chunks,
        )

    return system, user


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def parse_extraction_response(raw_response: str) -> dict:
    """Parse and validate the LLM JSON response.

    Returns the parsed dict. Raises ValueError with a descriptive message
    if the response is not valid JSON or does not match the expected schema.

    Caller is responsible for retry logic on ValueError.
    """
    try:
        data = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned non-JSON response: {exc}") from exc

    if "clauses" not in data or not isinstance(data["clauses"], list):
        raise ValueError(f"Response missing 'clauses' array: {list(data.keys())}")

    if "chunk_has_operative_content" not in data:
        raise ValueError("Response missing 'chunk_has_operative_content' field")

    required_clause_keys = {"clause_text", "starts_at_char", "ends_at_char", "is_continuation", "is_truncated"}
    for i, clause in enumerate(data["clauses"]):
        missing = required_clause_keys - set(clause.keys())
        if missing:
            raise ValueError(f"Clause {i} missing required keys: {missing}")
        if not isinstance(clause["clause_text"], str) or not clause["clause_text"].strip():
            raise ValueError(f"Clause {i} has empty clause_text")

    return data
