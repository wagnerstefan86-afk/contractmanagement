"""
Layout detection utilities: regex patterns and pure classification functions.

All functions are stateless and have no I/O — safe to import anywhere.
Used by Stage 1 (ingestion) to tag StructureElements and by Stage 2
(chunking) to make boundary decisions.
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Heading detection patterns
# ---------------------------------------------------------------------------

# German/Austrian/Swiss legal paragraph numbering.
# Matches: § 12, § 12a, § 12 Abs. 3, §12, § 12 Abs. 3 Satz 2
GERMAN_SECTION_RE = re.compile(
    r"^\s*§\s*\d+[a-z]?"
    r"(\s+(Abs\.|Absatz|Satz|Nr\.|Ziffer)\s*\d+)*",
    re.IGNORECASE,
)

# Numbered section headings. Intentionally does NOT match list items (handled
# separately): requires either a named keyword or a dot/space after the number.
#   Matches: 1. | 1.1 | 1.1.1 | Article 12 | Clause 5 | Section 3.2
#            Artikel 4 | Abschnitt 3 | Ziffer 2.1
NUMBERED_SECTION_RE = re.compile(
    r"^\s*("
    r"(?:Article|Clause|Section|Artikel|Abschnitt|Ziffer|Annex|Anlage|Schedule)\s+\d[\d.]*"
    r"|\d{1,3}(?:\.\d{1,3}){0,3}\.?\s"
    r")",
    re.IGNORECASE,
)

# Lettered / roman-numeral sub-items used as headings in some DE contracts.
# Only recognised as headings when word count is low (checked in caller).
LETTERED_HEADING_RE = re.compile(r"^\s*\([a-z]{1,3}\)\s|\([ivxlcdm]{1,6}\)\s", re.IGNORECASE)

# ---------------------------------------------------------------------------
# List item patterns
# ---------------------------------------------------------------------------

# Bullet characters and dash variants
BULLET_CHAR_RE = re.compile(r"^\s*[•·▪▸◦‣\-–—*]\s")

# Numbered list items: "1) text", "2. text" (NOT "1.1 text" which is a section)
NUMBERED_LIST_ITEM_RE = re.compile(r"^\s*\d{1,2}[)]\s")

# Lettered list items: "a) text", "(a) text", "a. text"
LETTERED_LIST_ITEM_RE = re.compile(r"^\s*(?:\(?[a-z]{1,2}\)?[.)]\s)", re.IGNORECASE)

# A paragraph that introduces a list: ends with a colon and is ≤ 40 words.
LIST_PREAMBLE_RE = re.compile(r":\s*$")

# ---------------------------------------------------------------------------
# Named standards (for specificity scoring, reused in Stage 6)
# ---------------------------------------------------------------------------

NAMED_STD_RE = re.compile(
    r"\b("
    r"ISO\s*\d+"
    r"|NIST(?:\s+SP\s+\d+[-\d]*)?"
    r"|SOC\s*[12]"
    r"|PCI[\s\-]?DSS"
    r"|GDPR|DSGVO"
    r"|NIS\s*2?"
    r"|DORA"
    r"|OWASP"
    r"|CIS\s+Controls?"
    r"|FedRAMP"
    r"|SSAE\s*\d+"
    r"|ISAE\s*\d+"
    r"|BSI(?:\s+IT-Grundschutz)?"
    r")\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Obligation language (for language_strength scoring in Stage 6)
# ---------------------------------------------------------------------------

SHALL_RE  = re.compile(r"\b(shall|muss|müssen|hat\s+zu|haben\s+zu)\b", re.IGNORECASE)
MUST_RE   = re.compile(r"\bmust\b", re.IGNORECASE)
WILL_RE   = re.compile(r"\bwill\b", re.IGNORECASE)
SHOULD_RE = re.compile(r"\b(should|sollte[n]?|is\s+required\s+to|sind\s+verpflichtet)\b", re.IGNORECASE)
MAY_RE    = re.compile(r"\b(may|kann|können|darf|dürfen)\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_heading(
    text: str,
    font_size: Optional[float],
    median_font_size: Optional[float],
) -> Optional[int]:
    """Return heading level (1, 2, or 3) or None if not a heading.

    Decision priority:
      1. Font-size ratio (PDF only) — most reliable signal
      2. German § pattern
      3. Numbered / named section pattern
      4. Short lettered sub-item (treated as level 3)

    Word-count guard: text with > 20 words is never classified as a heading
    regardless of font size, because headings are rarely that long.
    """
    stripped = text.strip()
    if not stripped:
        return None

    word_count = len(stripped.split())

    # Font-size heuristic (PDF only)
    if font_size and median_font_size and median_font_size > 0:
        ratio = font_size / median_font_size
        if ratio >= 1.20 and word_count <= 20:
            if ratio >= 1.50:
                return 1
            if ratio >= 1.30:
                return 2
            return 3

    if word_count > 20:
        return None

    if GERMAN_SECTION_RE.match(stripped):
        return 2

    if NUMBERED_SECTION_RE.match(stripped):
        # Estimate depth from dot count: "1." → 1, "1.1" → 2, "1.1.1" → 3
        m = re.match(r"^\s*(\d+(?:\.\d+)*)", stripped)
        if m:
            return min(m.group(1).count(".") + 1, 3)
        return 2

    if LETTERED_HEADING_RE.match(stripped) and word_count <= 10:
        return 3

    return None


def detect_bullet(text: str) -> bool:
    return bool(BULLET_CHAR_RE.match(text))


def detect_numbered_list_item(text: str) -> bool:
    return bool(NUMBERED_LIST_ITEM_RE.match(text) or LETTERED_LIST_ITEM_RE.match(text))


def is_list_preamble(text: str) -> bool:
    """True if a paragraph ends with ':' and is short enough to be a list intro."""
    stripped = text.strip()
    return bool(LIST_PREAMBLE_RE.search(stripped)) and len(stripped.split()) <= 40


def detect_language_strength(clause_text: str) -> tuple[float, str]:
    """Return (score 0.0–1.0, matched_pattern_label)."""
    if SHALL_RE.search(clause_text) or MUST_RE.search(clause_text):
        label = "shall" if SHALL_RE.search(clause_text) else "must"
        return 1.0, label
    if WILL_RE.search(clause_text):
        return 0.75, "will"
    if SHOULD_RE.search(clause_text):
        return 0.5, "should"
    if MAY_RE.search(clause_text):
        return 0.25, "may"
    return 0.1, "none"
