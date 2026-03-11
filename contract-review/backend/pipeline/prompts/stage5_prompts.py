"""
Stage 5 prompt templates.

Two prompt families:
  1. Clause normalization  — converts verbatim clause_text to a canonical
     active-voice obligation form. Used before embedding generation so that
     the normalized_embedding space is consistent across clauses and requirements.

  2. Requirement matching  — LLM semantic validation of whether a clause
     satisfies a specific compliance sub-requirement. Returns structured JSON
     with coverage, confidence, explanation, and missing elements.
"""

from __future__ import annotations

from typing import Optional

# ===========================================================================
# 1. CLAUSE NORMALIZATION
# ===========================================================================
#
# Goal: convert verbatim contract language into a canonical form that
# collapses linguistic variation (passive/active voice, modal verbs, word
# order) so that embeddings of obligations with equivalent semantics cluster
# together.
#
# Canonical form rules:
#   - Active voice (subject first)
#   - Subject is the obligated party ("supplier", "customer", "both parties")
#   - Canonical obligation verb: "must" (replaces shall/will/is required to)
#   - Scope/object after the verb
#   - Time constraint appended last
#   - All lowercase, no punctuation except commas and hyphens in compound terms
#   - If the clause contains multiple distinct obligations, return one normalized
#     sentence per obligation separated by " | "
# ---------------------------------------------------------------------------

NORMALIZATION_SYSTEM = """\
You are a legal language normalization specialist. Your task is to convert \
verbatim contract clause text into a canonical active-voice obligation form.

Canonical form rules:
- Active voice: subject before verb
- Subject = the obligated party (use "supplier", "customer", or "both parties")
- Obligation verb: always "must" (replace shall/will/is required to/has to)
- Scope or object follows the verb
- Time constraint appended at the end, if present
- All lowercase; no trailing punctuation; no bullet markers
- If the clause has multiple distinct obligations, separate them with " | "
- If the clause is purely definitional (no obligation), return an empty string

Return ONLY valid JSON — no additional text.\
"""

NORMALIZATION_USER_TEMPLATE = """\
Normalize the following contract clause to canonical active-voice obligation form.

CLAUSE CATEGORY: {primary_category}
SECTION REFERENCE: {section_reference}

CLAUSE TEXT:
---
{clause_text}
---

Return JSON matching this schema:
{{
  "normalized_clause": "<canonical form, or empty string if no obligation>",
  "obligated_party": "<supplier | customer | both_parties | unspecified>",
  "obligation_verb_found": "<original modal/verb phrase that was normalized, e.g. 'shall', 'is required to'>",
  "has_time_constraint": <boolean>,
  "normalization_notes": "<optional: note any ambiguity or multi-obligation split>"
}}

Example input:
  "Incidents shall be reported within 24 hours by the supplier"

Example output:
{{
  "normalized_clause": "supplier must report incidents within 24 hours",
  "obligated_party": "supplier",
  "obligation_verb_found": "shall",
  "has_time_constraint": true,
  "normalization_notes": ""
}}\
"""

# Expected JSON output structure (for parse_normalization_response):
# {
#   "normalized_clause": str,          — empty string if definitional only
#   "obligated_party": str,            — supplier | customer | both_parties | unspecified
#   "obligation_verb_found": str,      — original verb phrase
#   "has_time_constraint": bool,
#   "normalization_notes": str
# }

NORMALIZATION_REQUIRED_KEYS = {
    "normalized_clause",
    "obligated_party",
    "obligation_verb_found",
    "has_time_constraint",
}


def build_normalization_messages(
    clause_text: str,
    primary_category: str,
    section_reference: Optional[str],
) -> tuple[str, str]:
    user = NORMALIZATION_USER_TEMPLATE.format(
        clause_text=clause_text,
        primary_category=primary_category,
        section_reference=section_reference or "Not specified",
    )
    return NORMALIZATION_SYSTEM, user


# ===========================================================================
# 2. REQUIREMENT MATCHING (LLM SEMANTIC VALIDATION)
# ===========================================================================
#
# Called for every (clause, sub_requirement) pair that passes Pass 1
# (embedding_similarity >= threshold). Determines whether the clause
# actually satisfies the sub-requirement and to what degree.
#
# The prompt receives:
#   - Full clause_text (verbatim) and normalized_clause
#   - Sub-requirement description and evidence_keywords
#   - Pre-computed quality signals (language_strength, quality_band)
#   - Embedding similarity score from Pass 1
# ---------------------------------------------------------------------------

MATCHING_SYSTEM = """\
You are a compliance assessment specialist with deep expertise in ISO 27001, \
GDPR, DORA, and NIS2. Assess whether a contract clause satisfies a specific \
compliance sub-requirement.

COVERAGE LEVELS:
- full:    The clause explicitly, completely, and unconditionally satisfies all \
required elements of the sub-requirement. No material gaps.
- partial: The clause addresses the sub-requirement but has gaps — missing \
elements, insufficient specificity, scope limitations, or weakening modifiers.
- none:    The clause does not address the sub-requirement at all, or \
addresses it in a way that is contradictory or wholly insufficient.

Be conservative: if uncertain between "full" and "partial", return "partial".
If uncertain between "partial" and "none", return "partial" only if at least \
one core element of the requirement is present in the clause.

Return ONLY valid JSON — no additional text.\
"""

MATCHING_USER_TEMPLATE = """\
Assess whether the following contract clause satisfies the specified \
compliance sub-requirement.

─── FRAMEWORK ────────────────────────────────────────────────────────────
Framework:          {framework_id} ({framework_name})
Sub-requirement ID: {sub_requirement_id}
Sub-requirement:    {sub_requirement_description}
Evidence keywords:  {evidence_keywords}

─── CONTRACT CLAUSE ──────────────────────────────────────────────────────
Verbatim text:
---
{clause_text}
---
Normalized form: {normalized_clause}
Section:         {section_reference}

─── PRE-COMPUTED SIGNALS ─────────────────────────────────────────────────
Embedding similarity (Pass 1): {embedding_similarity:.3f}
Language strength:             {language_strength:.2f}  ({language_label})
Quality band:                  {quality_band}
Active modifiers:              {modifiers}

─── RESPONSE SCHEMA ──────────────────────────────────────────────────────
Return JSON:
{{
  "requirement_match": <boolean — true if coverage is full or partial>,
  "confidence": <float 0.0–1.0>,
  "coverage": "<full | partial | none>",
  "explanation": "<2–4 sentences referencing specific clause text and the regulatory requirement>",
  "missing_elements": ["<element from evidence_keywords not satisfied>", ...]
}}

Example (partial coverage):
{{
  "requirement_match": true,
  "confidence": 0.82,
  "coverage": "partial",
  "explanation": "The clause establishes a 24-hour notification window, satisfying \
the core GDPR Article 33 timing requirement. However, it omits the required \
notification content (Article 33(3)(a-d): nature of breach, likely consequences, \
measures taken) and does not address the phased notification mechanism of Article 33(4).",
  "missing_elements": [
    "notification content requirements (GDPR Art 33(3))",
    "phased notification mechanism (GDPR Art 33(4))",
    "DPO contact details"
  ]
}}\
"""

MATCHING_REQUIRED_KEYS = {"requirement_match", "confidence", "coverage", "explanation", "missing_elements"}
VALID_COVERAGE_VALUES  = {"full", "partial", "none"}


def build_matching_messages(
    clause_text: str,
    normalized_clause: Optional[str],
    section_reference: Optional[str],
    sub_requirement_id: str,
    sub_requirement_description: str,
    framework_id: str,
    framework_name: str,
    evidence_keywords: list[str],
    embedding_similarity: float,
    language_strength: float,
    quality_band: str,
    modifier_types: list[str],
) -> tuple[str, str]:
    language_label = _language_label(language_strength)
    modifiers_str  = ", ".join(modifier_types) if modifier_types else "none"
    keywords_str   = ", ".join(f'"{k}"' for k in evidence_keywords) if evidence_keywords else "none specified"

    user = MATCHING_USER_TEMPLATE.format(
        framework_id=framework_id,
        framework_name=framework_name,
        sub_requirement_id=sub_requirement_id,
        sub_requirement_description=sub_requirement_description,
        evidence_keywords=keywords_str,
        clause_text=clause_text,
        normalized_clause=normalized_clause or "(not yet normalized)",
        section_reference=section_reference or "Not specified",
        embedding_similarity=embedding_similarity,
        language_strength=language_strength,
        language_label=language_label,
        quality_band=quality_band,
        modifiers=modifiers_str,
    )
    return MATCHING_SYSTEM, user


def _language_label(score: float) -> str:
    if score >= 1.0:
        return "shall / must — mandatory"
    if score >= 0.75:
        return "will — obligation with slight ambiguity"
    if score >= 0.5:
        return "should / is required to — recommended"
    if score >= 0.25:
        return "may — permissive"
    return "none detected"
