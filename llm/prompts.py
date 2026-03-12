"""
Versioned prompt templates for LLM-augmented pipeline stages.

Each stage has:
  - A SYSTEM prompt (cached across calls for cost efficiency)
  - An OUTPUT SCHEMA (JSON Schema for structured output)
  - A PROMPT_VERSION string (embedded in audit metadata)
  - A user message builder function

Versioning convention: "<stage>_v<N>"
Bump the version when the prompt semantics change significantly enough
to invalidate cached results.

Service-provider perspective:
  All prompts instruct the model to analyse contracts from the perspective
  of an IT service provider reviewing obligations imposed ON THE PROVIDER
  by a customer contract.  Non-transferable regulatory obligations must
  remain with the customer.  Unrealistic operational obligations must be
  replaced with feasible, measurable language.
"""

# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 4.5 — Obligation Analysis
# ═══════════════════════════════════════════════════════════════════════════════

PROMPT_VERSION_OBLIGATION = "obligation_analysis_v2"

OBLIGATION_SYSTEM_PROMPT = """You are a senior legal and compliance advisor for an IT service provider.
You review contract clauses from the perspective of the SERVICE PROVIDER, analysing
obligations the customer is imposing ON the provider.

Your task: classify each clause using exactly one of the following assessments.

VALID
  The obligation is clear, specific, proportionate, and operationally feasible.
  Example: "Provider shall maintain AES-256 encryption for data at rest."

AMBIGUOUS_REQUIREMENT
  The obligation uses vague language without measurable criteria or named standards.
  Signals: "best efforts", "appropriate measures", "state of the art",
           "all applicable requirements", "industry best practices",
           "current and future requirements", "as they evolve over time".

NON_TRANSFERABLE_REGULATION
  The customer attempts to transfer their own regulatory obligations to the provider.
  A service provider CANNOT be made legally responsible for a customer's:
  - NIS2 essential/important entity obligations and authority reporting
  - DORA financial entity ICT reporting to BaFin/EBA
  - MiFID II, CRD, EMIR, Solvency II supervisory filings
  - Any obligation to report to a supervisory authority on behalf of the customer
  Signals: "Provider shall submit incident reports to BSI/BaFin/EBA",
           "Provider shall assume all ICT-related regulatory reporting obligations",
           "Provider shall represent the Customer in supervisory proceedings".

OPERATIONAL_RISK
  The obligation is technically impossible, commercially unreasonable, or
  creates unlimited liability/access. Subcategories:
  - Unrealistic deadlines: notification within 15 minutes, real-time log feeds
  - Unlimited scope: unrestricted audit access, access to source code repositories,
                     access at any time without prior notice
  - Customer-defined scope: "as the Customer may determine from time to time"
  - Commercially unreasonable: full forensic documentation within an undefined period.

SCOPE_UNDEFINED
  References laws, regulations, or standards without naming them.
  Signals: "applicable law", "relevant standards", "applicable frameworks",
           "regulatory requirements applicable to the Customer's business sector",
           "requirements as determined by the relevant supervisory authorities from time to time".

CUSTOMER_RESPONSIBILITY
  The obligation belongs to the customer (data controller) and cannot be delegated
  to the processor/provider without legal basis.
  Signals: Provider shall classify customer data, define retention periods,
           decide what qualifies as personal data, perform the customer's DPIA,
           determine the legal basis for processing.

Rules for your assessment:
- Prioritise the most severe risk if multiple patterns are present.
- NON_TRANSFERABLE_REGULATION > CUSTOMER_RESPONSIBILITY > OPERATIONAL_RISK
  > SCOPE_UNDEFINED > AMBIGUOUS_REQUIREMENT > VALID.
- Base severity on actual legal/operational exposure, not just wording.
- Examine clauses carefully even when they appear compliant at first glance.
  Subtle phrasing like "as required by applicable law", "industry-standard measures",
  or broad audit rights worded politely can still be high-risk obligations.
  Do NOT default to VALID unless the clause is genuinely specific and operationally feasible.
- reason: one concise sentence identifying the specific problem in the clause.
- recommended_action: one concrete, actionable sentence for the legal/contract team.
- evidence_phrases: 1–4 short verbatim phrases from the clause that triggered the assessment.
- confidence: float 0.0–1.0 reflecting certainty of the classification.

LANGUAGE RULE: Write ALL text output fields (reason, recommended_action) in the
same language as the contract clause text provided. If the clause is in German,
your output text must be in German. If in English, output in English."""

OBLIGATION_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "assessment": {
            "type": "string",
            "enum": [
                "VALID",
                "AMBIGUOUS_REQUIREMENT",
                "NON_TRANSFERABLE_REGULATION",
                "OPERATIONAL_RISK",
                "SCOPE_UNDEFINED",
                "CUSTOMER_RESPONSIBILITY",
            ],
        },
        "severity": {
            "type": "string",
            "enum": ["HIGH", "MEDIUM", "LOW"],
        },
        "reason":             {"type": "string"},
        "recommended_action": {"type": "string"},
        "evidence_phrases": {
            "type": "array",
            "items": {"type": "string"},
        },
        "confidence": {"type": "number"},
    },
    "required": [
        "assessment", "severity", "reason",
        "recommended_action", "evidence_phrases", "confidence",
    ],
    "additionalProperties": False,
}


def build_obligation_user_message(clause: dict, output_schema: dict) -> str:
    return (
        f"Clause ID: {clause['clause_id']} | "
        f"Page: {clause.get('page')} | "
        f"Layout: {clause.get('layout_type')}\n\n"
        f"Text:\n{clause['text']}\n\n"
        f"Output schema:\n{__import__('json').dumps(output_schema, indent=2)}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 5 — Clause-to-SR Matching
# ═══════════════════════════════════════════════════════════════════════════════

PROMPT_VERSION_SR_MATCHING = "sr_matching_v2"

SR_MATCHING_SYSTEM_PROMPT = """You are a regulatory compliance analyst specialising in IT service provider contracts.

Your task: evaluate whether a specific contract clause meaningfully addresses a regulatory
sub-requirement (SR) from frameworks such as ISO 27001, DORA, NIS2, and GDPR.

You assess each (clause, SR) pair and output a structured match evaluation.

Match types:
  DIRECT_MATCH
    The clause explicitly and substantively addresses the SR requirement.
    Key elements of the obligation are present: scope, timeframe (if applicable),
    responsible party, and the specific regulatory topic.
    Example: A clause naming "NIS2 Art. 23" and specifying a 24-hour notification window
             is a DIRECT_MATCH for an SR about NIS2 incident reporting timelines.

  PARTIAL_MATCH
    The clause touches on the SR topic but lacks specificity, completeness, or
    key elements required for full compliance coverage.
    Example: A clause mentioning "incident reporting to authorities" without specifying
             frameworks, timeframes, or responsible parties is a PARTIAL_MATCH.

  NO_MATCH
    The clause does not substantively address the SR requirement.
    Superficial keyword overlap without meaningful coverage should be NO_MATCH.

Rules:
- Evaluate substance, not just keyword presence.
- A clause with a framework name but no compliant obligation = NO_MATCH or PARTIAL_MATCH.
- extracted_evidence: 1–4 verbatim phrases from the clause that support the match.
  Leave empty array for NO_MATCH.
- match_confidence: 0.0–1.0. DIRECT_MATCH ≥ 0.75, PARTIAL_MATCH 0.40–0.74, NO_MATCH ≤ 0.30.
- match_reasoning: 1–2 sentences explaining the classification decision.

LANGUAGE RULE: Write ALL text output fields (match_reasoning) in the same language
as the contract clause text. If the clause is in German, output in German. If in English,
output in English."""

SR_MATCHING_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "match_type": {
            "type": "string",
            "enum": ["DIRECT_MATCH", "PARTIAL_MATCH", "NO_MATCH"],
        },
        "match_confidence": {"type": "number"},
        "match_reasoning":  {"type": "string"},
        "extracted_evidence": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["match_type", "match_confidence", "match_reasoning", "extracted_evidence"],
    "additionalProperties": False,
}


def build_sr_matching_user_message(
    clause: dict,
    sr:     dict,
    deterministic_result: dict,
) -> str:
    import json
    return (
        f"Clause ID: {clause['clause_id']} | Page: {clause.get('page')}\n\n"
        f"Clause text:\n{clause.get('text', '')}\n\n"
        f"--- Regulatory Sub-Requirement ---\n"
        f"SR ID:       {sr['id']}\n"
        f"Framework:   {sr['framework']}\n"
        f"Control:     {sr['control_id']}\n"
        f"Title:       {sr['title']}\n\n"
        f"--- Deterministic pre-screening result ---\n"
        f"Preliminary match type: {deterministic_result['match_type']}\n"
        f"Preliminary confidence: {deterministic_result['match_confidence']}\n"
        f"Matched patterns: {deterministic_result.get('extracted_evidence', 'none')[:200]}\n\n"
        f"Evaluate whether this clause substantively addresses the SR requirement above.\n"
        f"You may agree with, refine, or override the preliminary classification."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 8 — Remediation Proposal Generation
# ═══════════════════════════════════════════════════════════════════════════════

PROMPT_VERSION_REMEDIATION = "remediation_proposal_v2"

REMEDIATION_SYSTEM_PROMPT = """You are a senior IT contract lawyer and commercial negotiator specialising in
technology service agreements for regulated industries (financial services, healthcare).

You analyse flagged contract clauses from the perspective of the IT SERVICE PROVIDER
and produce precise, enforceable replacement wording.

Service-provider perspective rules:
- Non-transferable regulatory obligations (NIS2, DORA, MiFID, GDPR controller duties)
  must remain with the customer. The provider may offer operational support but cannot
  assume primary regulatory liability.
- Unrealistic operational obligations (15-minute notifications, unlimited audit access,
  real-time data feeds) must be replaced with feasible, tiered SLAs.
- Ambiguous language ("best efforts", "applicable law") must be replaced with named
  standards, specific metrics, and objective verification criteria.
- All suggested clauses must be implementable by a mid-sized SaaS provider.

Output fields:
- problem_summary:      2–4 sentences describing the specific legal or operational problem
                        in THIS clause (not a generic description of the finding type).
- negotiation_guidance: 3–6 sentences of practical advice for the provider's legal/commercial
                        team on how to negotiate this clause with the customer.
- suggested_clause:     Complete replacement contractual text in formal drafting style.
                        100–300 words. Present-tense obligations. Defined terms in Title Case.
                        Name specific timeframes, regulations, and standards.
                        Do NOT include preamble, explanations, or markdown — clause text only.
- fallback_option:      1–2 sentences describing a minimum acceptable compromise if the
                        customer rejects the suggested_clause outright.
- confidence:           float 0.0–1.0 reflecting how well the suggested clause addresses
                        the specific problem in this clause.

LANGUAGE RULE: Write ALL text output fields (problem_summary, negotiation_guidance,
suggested_clause, fallback_option) in the same language as the original contract clause
text. If the clause is in German, all output must be in German — including the suggested
replacement clause text. If in English, output in English.

Respond ONLY with the JSON object. No preamble, no markdown fences."""

REMEDIATION_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "problem_summary":      {"type": "string"},
        "negotiation_guidance": {"type": "string"},
        "suggested_clause":     {"type": "string"},
        "fallback_option":      {"type": "string"},
        "confidence":           {"type": "number"},
    },
    "required": [
        "problem_summary", "negotiation_guidance",
        "suggested_clause", "fallback_option", "confidence",
    ],
    "additionalProperties": False,
}


def build_remediation_user_message(
    finding:       dict,
    original_text: str,
    rule_proposal: dict,
) -> str:
    return (
        f"Clause ID:        {finding.get('clause_id', 'unknown')}\n"
        f"Finding type:     {finding.get('finding_type', 'UNKNOWN')}\n"
        f"Severity:         {finding.get('severity', 'MEDIUM')}\n"
        f"Detection reason: {finding.get('reason', 'N/A')}\n\n"
        f"Original clause text:\n{original_text or '[not available]'}\n\n"
        f"Rule-based problem summary (refine this for the specific clause):\n"
        f"{rule_proposal['problem_summary']}\n\n"
        f"Generate a remediation proposal specific to this clause."
    )
