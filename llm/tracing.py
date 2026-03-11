"""
Explainability and reviewer routing metadata utilities.

Provides helper functions to compute the five transparency fields added to
Stage 4.5, Stage 5, and Stage 8 outputs:

  _baseline_result    — compact deterministic result captured before AI merge;
                        null when no AI was attempted (source == 'rule_based')
  _decision_delta     — how AI changed the outcome vs baseline:
                        'no_change' / 'ai_upgrade' / 'ai_downgrade' / 'ai_override'
                        null when no AI was attempted
  _confidence_bucket  — 'high' (≥0.85) / 'medium' (≥0.60) / 'low' (<0.60);
                        derived from AI confidence; null when no AI attempted
  _review_priority    — human-reviewer routing: 'HIGH' / 'MEDIUM' / 'LOW';
                        computed for ALL records (deterministic and AI-enhanced)
  _ai_trace           — {analysis_type, decision_basis: [str], evidence_tokens: [str]};
                        null when no AI was attempted or LLM response was None

No external dependencies — safe to import independently of LLM provider availability.
"""
from __future__ import annotations

from typing import Optional

# ── Ordering tables ────────────────────────────────────────────────────────────

_SEV_ORDER   = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_MATCH_ORDER = {"NO_MATCH": 0, "PARTIAL_MATCH": 1, "DIRECT_MATCH": 2}


# ── Confidence bucketing ───────────────────────────────────────────────────────

def confidence_bucket(confidence: Optional[float]) -> Optional[str]:
    """
    Map a raw confidence score to a human-readable bucket.

    Returns 'high' (≥0.85), 'medium' (≥0.60), 'low' (<0.60).
    Returns None when confidence is None (no AI used).
    """
    if confidence is None:
        return None
    if confidence >= 0.85:
        return "high"
    if confidence >= 0.60:
        return "medium"
    return "low"


# ── Decision delta ─────────────────────────────────────────────────────────────

def decision_delta_assessment(
    baseline_assessment: str,
    baseline_severity:   str,
    final_assessment:    str,
    final_severity:      str,
    ai_attempted:        bool,
) -> Optional[str]:
    """
    Stage 4.5 — compare baseline deterministic result vs merged final.

    Returns:
        None            — no AI attempted (source == 'rule_based')
        'no_change'     — AI agreed with deterministic on both assessment and severity
        'ai_upgrade'    — AI raised severity (found issue more serious)
        'ai_downgrade'  — AI lowered severity (found issue less serious)
        'ai_override'   — same severity but AI changed assessment category
    """
    if not ai_attempted:
        return None
    if baseline_assessment == final_assessment and baseline_severity == final_severity:
        return "no_change"
    base_sev  = _SEV_ORDER.get(baseline_severity,  0)
    final_sev = _SEV_ORDER.get(final_severity, 0)
    if final_sev > base_sev:
        return "ai_upgrade"
    if final_sev < base_sev:
        return "ai_downgrade"
    return "ai_override"  # same severity, different assessment


def decision_delta_match(
    baseline_match_type: str,
    final_match_type:    str,
    ai_attempted:        bool,
) -> Optional[str]:
    """
    Stage 5 — compare baseline deterministic match vs merged final.

    Returns:
        None            — no AI attempted
        'no_change'     — AI confirmed deterministic match_type
        'ai_upgrade'    — AI raised match level (e.g. PARTIAL → DIRECT)
        'ai_downgrade'  — AI lowered match level (e.g. DIRECT → PARTIAL/NO_MATCH)
    """
    if not ai_attempted:
        return None
    if baseline_match_type == final_match_type:
        return "no_change"
    base_rank  = _MATCH_ORDER.get(baseline_match_type,  0)
    final_rank = _MATCH_ORDER.get(final_match_type, 0)
    if final_rank > base_rank:
        return "ai_upgrade"
    return "ai_downgrade"


def decision_delta_proposal(proposal_src: str) -> Optional[str]:
    """
    Stage 8 — delta based on proposal source label.

    Returns:
        None            — 'rule_based' (no AI attempted)
        'no_change'     — 'hybrid': AI tried but low confidence; rule kept
        'ai_override'   — 'llm': AI proposal used instead of rule template
    """
    if proposal_src == "rule_based":
        return None
    if proposal_src == "hybrid":
        return "no_change"
    if proposal_src == "llm":
        return "ai_override"
    return None


# ── Review priority ────────────────────────────────────────────────────────────

def review_priority_obligation(
    assessment:  str,
    severity:    str,
    conf_bucket: Optional[str],
) -> str:
    """
    Stage 4.5 reviewer routing — computed for every record, including deterministic.

    HIGH  : low confidence OR HIGH severity OR NON_TRANSFERABLE_REGULATION OR OPERATIONAL_RISK
    MEDIUM: medium confidence OR AMBIGUOUS_REQUIREMENT OR SCOPE_UNDEFINED
    LOW   : otherwise
    """
    if (conf_bucket == "low"
            or severity == "HIGH"
            or assessment in ("NON_TRANSFERABLE_REGULATION", "OPERATIONAL_RISK")):
        return "HIGH"
    if (conf_bucket == "medium"
            or assessment in ("AMBIGUOUS_REQUIREMENT", "SCOPE_UNDEFINED")):
        return "MEDIUM"
    return "LOW"


def review_priority_match(
    match_type:     str,
    conf_bucket:    Optional[str],
    decision_delta: Optional[str],
) -> str:
    """
    Stage 5 reviewer routing — computed for every record.

    HIGH  : low confidence OR AI changed match_type (upgrade or downgrade)
    MEDIUM: medium confidence OR match_type == PARTIAL_MATCH
    LOW   : otherwise
    """
    if conf_bucket == "low" or decision_delta in ("ai_upgrade", "ai_downgrade"):
        return "HIGH"
    if conf_bucket == "medium" or match_type == "PARTIAL_MATCH":
        return "MEDIUM"
    return "LOW"


def review_priority_proposal(
    finding_type:     str,
    conf_bucket:      Optional[str],
    suggested_clause: str,
) -> str:
    """
    Stage 8 reviewer routing — computed for every record.

    HIGH  : low confidence OR empty suggested_clause OR NON_TRANSFERABLE_REGULATION/OPERATIONAL_RISK
    MEDIUM: medium confidence
    LOW   : otherwise
    """
    if (conf_bucket == "low"
            or not suggested_clause.strip()
            or finding_type in ("NON_TRANSFERABLE_REGULATION", "OPERATIONAL_RISK")):
        return "HIGH"
    if conf_bucket == "medium":
        return "MEDIUM"
    return "LOW"


# ── AI trace builders ──────────────────────────────────────────────────────────

def build_obligation_trace(
    llm_content: Optional[dict],
    source:      str,
) -> Optional[dict]:
    """
    Compact trace for a Stage 4.5 LLM call.
    Returns None when source != 'llm' or llm_content is None.
    """
    if source != "llm" or llm_content is None:
        return None
    evidence = llm_content.get("evidence_phrases", [])
    if isinstance(evidence, str):
        evidence = [evidence] if evidence else []
    return {
        "analysis_type": "obligation_classification",
        "decision_basis": [
            f"assessment={llm_content.get('assessment')}",
            f"severity={llm_content.get('severity')}",
            f"confidence={llm_content.get('confidence')}",
        ],
        "evidence_tokens": list(evidence)[:6],
    }


def build_sr_match_trace(
    baseline_match_type: str,
    llm_content:         Optional[dict],
    source:              str,
) -> Optional[dict]:
    """
    Compact trace for a Stage 5 LLM call.
    Returns None when source is 'rule_based' or llm_content is None.
    """
    if source == "rule_based" or llm_content is None:
        return None
    evidence = llm_content.get("extracted_evidence", [])
    if isinstance(evidence, str):
        evidence = [evidence] if evidence else []
    elif not isinstance(evidence, list):
        evidence = []
    return {
        "analysis_type": "sr_match_validation",
        "decision_basis": [
            f"baseline={baseline_match_type}",
            f"final={llm_content.get('match_type')}",
            f"confidence={llm_content.get('match_confidence')}",
        ],
        "evidence_tokens": list(evidence)[:4],
    }


def build_remediation_trace(
    finding_type: str,
    llm_content:  Optional[dict],
    source:       str,
) -> Optional[dict]:
    """
    Compact trace for a Stage 8 LLM call.
    Returns None when source is 'rule_based' or llm_content is None.
    """
    if source == "rule_based" or llm_content is None:
        return None
    return {
        "analysis_type": "remediation_proposal",
        "decision_basis": [
            f"finding_type={finding_type}",
            f"confidence={llm_content.get('confidence')}",
            f"source={source}",
        ],
        "evidence_tokens": [],
    }
