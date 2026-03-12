#!/usr/bin/env python3
"""
Stage 3 — Contract Classification Engine

Classifies a contract document using a two-pass approach:
  1. Rule-based keyword scoring (always runs, zero dependencies)
  2. LLM refinement via Claude API (runs when ANTHROPIC_API_KEY is set)

Results are merged deterministically: LLM output dominates when confidence >= 0.75,
otherwise rule-based result is used.

SCOPE BOUNDARY — Stage 3 determines ONLY:
  - contract_type       (SAAS / CLOUD_HOSTING / MSP / DATA_PROCESSING / ICT_OUTSOURCING / OTHER)
  - vendor_risk_tier    (LOW / MEDIUM / HIGH / CRITICAL)
  - data_sensitivity    (PUBLIC / INTERNAL / CONFIDENTIAL / PERSONAL_DATA / SPECIAL_CATEGORY)

Regulatory frameworks are NOT inferred here. They are loaded exclusively from
org_profile.json by Stage 5, which is the single authoritative source.

Usage:
    python stage3_contract_classification.py contract_chunks.json [options]

Options:
    --contract-id  <id>   Contract identifier (default: CT-2026-001)
    --no-llm              Skip LLM pass (rule-based only)
    --output      <path>  Output file path (default: contract_metadata.json)

Output:
    contract_metadata.json — consumed by Stage 5 matching engine
"""

import json
import sys
import os
import argparse
import logging
from collections import defaultdict
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("stage3")

# Optional — LLM pass requires `pip install anthropic`
try:
    import anthropic
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False

# ---------------------------------------------------------------------------
# Classification keyword maps
# ---------------------------------------------------------------------------

CONTRACT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "SAAS": [
        "subscription", "saas", "software as a service", "access to platform",
        "uptime", "service level agreement", "tenant", "multitenant",
        "per seat", "per user", "monthly fee", "annual subscription",
        "web-based", "cloud application", "hosted service", "sla",
    ],
    "CLOUD_HOSTING": [
        "infrastructure", "compute", "storage", "virtual machine",
        "region", "availability zone", "bare metal", "iaas", "paas",
        "container", "kubernetes", "load balancer", "cdn", "bandwidth",
        "data center", "colocation", "hosting services",
    ],
    "MSP": [
        "managed service", "managed services provider", "msp",
        "monitoring", "patching", "patch management", "helpdesk",
        "it operations", "noc", "network operations", "service desk",
        "incident management", "change management", "proactive support",
    ],
    "DATA_PROCESSING": [
        "data processor", "data controller", "processor", "controller",
        "gdpr art. 28", "article 28", "data processing agreement", "dpa",
        "personal data", "data subject", "processing activities",
        "subprocessor", "sub-processor",
    ],
    "ICT_OUTSOURCING": [
        "financial entity", "dora", "ict", "information and communication technology",
        "operational dependency", "critical function", "outsourcing",
        "ict outsourcing", "third-party ict", "eba", "bafin",
        "systemic risk", "concentration risk", "regulation (eu) 2022/2554",
    ],
}

DATA_SENSITIVITY_KEYWORDS: dict[str, list[str]] = {
    "SPECIAL_CATEGORY": [
        "health data", "biometric", "genetic", "racial origin", "ethnic origin",
        "political opinion", "religious belief", "trade union", "sexual",
        "criminal conviction", "art. 9", "article 9", "gdpr art. 9",
    ],
    "PERSONAL_DATA": [
        "personal data", "personally identifiable", "pii", "data subject",
        "name", "email address", "phone number", "ip address", "cookie",
        "gdpr", "dsgvo", "ccpa", "privacy", "natural person",
    ],
    "CONFIDENTIAL": [
        "confidential", "proprietary", "trade secret", "nda",
        "non-disclosure", "restricted", "sensitive business",
    ],
    "INTERNAL": [
        "internal use", "employee data", "staff", "business information",
        "internal documents", "internal only",
    ],
    "PUBLIC": [
        "public data", "publicly available", "open data",
    ],
}

# Vendor risk tier rules — evaluated in order, first match wins
# Each entry: (condition_fn(contract_type, data_sensitivity), tier, reason)
# NOTE: regulatory_scope is intentionally NOT a parameter — it is owned by org_profile.json
VENDOR_RISK_RULES = [
    (
        lambda ct, ds: ds in ("PERSONAL_DATA", "SPECIAL_CATEGORY") and ct == "ICT_OUTSOURCING",
        "CRITICAL",
        "ICT outsourcing provider processing personal data — maximum exposure",
    ),
    (
        lambda ct, ds: ds in ("PERSONAL_DATA", "SPECIAL_CATEGORY"),
        "CRITICAL",
        "Vendor processes personal or special-category data — GDPR Art. 28 obligations apply",
    ),
    (
        lambda ct, ds: ct == "CLOUD_HOSTING",
        "CRITICAL",
        "Infrastructure/hosting provider — direct operational dependency",
    ),
    (
        lambda ct, ds: ct == "ICT_OUTSOURCING",
        "CRITICAL",
        "ICT outsourcing — critical third-party dependency",
    ),
    (
        lambda ct, ds: ct == "DATA_PROCESSING",
        "HIGH",
        "Dedicated data processor — elevated privacy and regulatory liability",
    ),
    (
        lambda ct, ds: ct == "MSP" and ds == "CONFIDENTIAL",
        "HIGH",
        "MSP with confidential data access — security monitoring and identity exposure",
    ),
    (
        lambda ct, ds: ct == "MSP",
        "HIGH",
        "Managed service provider — security monitoring and privileged access",
    ),
    (
        lambda ct, ds: ct == "SAAS" and ds in ("CONFIDENTIAL", "PERSONAL_DATA"),
        "MEDIUM",
        "SaaS platform handling confidential or personal data",
    ),
    (
        lambda ct, ds: ct == "SAAS",
        "MEDIUM",
        "SaaS tool with internal business data",
    ),
    (
        lambda ct, ds: True,
        "LOW",
        "Default — non-sensitive tooling or minimal data exposure",
    ),
]

# LLM output JSON schema — regulatory_scope intentionally ABSENT (owned by org_profile)
LLM_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "contract_type": {
            "type": "string",
            "enum": ["SAAS", "CLOUD_HOSTING", "MSP", "DATA_PROCESSING", "ICT_OUTSOURCING", "OTHER"],
        },
        "vendor_risk_tier": {
            "type": "string",
            "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
        },
        "data_sensitivity": {
            "type": "string",
            "enum": ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "PERSONAL_DATA", "SPECIAL_CATEGORY"],
        },
        "confidence": {"type": "number"},
        "reasoning":  {"type": "string"},
    },
    "required": ["contract_type", "vendor_risk_tier", "data_sensitivity", "confidence", "reasoning"],
    "additionalProperties": False,
}

LLM_SYSTEM_PROMPT = """You are an expert contract compliance analyst specializing in InfoSec
and data protection law.

Analyze the provided contract text and classify it accurately.
Determine ONLY: contract_type, vendor_risk_tier, data_sensitivity, and confidence.
Do NOT classify regulatory frameworks — that is determined by the organization's profile.
Respond ONLY with a valid JSON object matching the specified schema.
Be conservative: when in doubt, escalate data sensitivity and vendor risk tier.
Confidence must be a float between 0.0 and 1.0."""


# ---------------------------------------------------------------------------
# Rule-based classifier helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return text.lower().replace("-", " ").replace("_", " ")


def _score_keywords(
    text: str, keyword_map: dict[str, list[str]]
) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Return (hit_counts, matched_keywords) per category."""
    text_n = _normalize(text)
    scores: dict[str, int] = defaultdict(int)
    signals: dict[str, list[str]] = defaultdict(list)
    for category, keywords in keyword_map.items():
        for kw in keywords:
            if kw in text_n:
                scores[category] += 1
                signals[category].append(kw)
    return dict(scores), dict(signals)


def _classify_contract_type(
    text: str,
) -> tuple[str, float, dict[str, list[str]]]:
    scores, signals = _score_keywords(text, CONTRACT_TYPE_KEYWORDS)
    if not scores:
        return "OTHER", 0.50, {}
    top = max(scores, key=scores.get)  # type: ignore[arg-type]
    total = sum(scores.values())
    # Confidence: proportion of hits going to winner, boosted by absolute hit count
    raw_conf = scores[top] / max(total, 1)
    abs_boost = min(scores[top] * 0.03, 0.20)
    confidence = round(min(0.45 + raw_conf * 0.5 + abs_boost, 0.95), 2)
    return top, confidence, signals


def _classify_data_sensitivity(
    text: str,
) -> tuple[str, dict[str, list[str]]]:
    scores, signals = _score_keywords(text, DATA_SENSITIVITY_KEYWORDS)
    priority = ["SPECIAL_CATEGORY", "PERSONAL_DATA", "CONFIDENTIAL", "INTERNAL", "PUBLIC"]
    for level in priority:
        if scores.get(level, 0) > 0:
            return level, signals
    return "INTERNAL", {}  # conservative default when no keywords match


def _resolve_vendor_risk_tier(
    contract_type: str,
    data_sensitivity: str,
) -> tuple[str, str]:
    for condition_fn, tier, reason in VENDOR_RISK_RULES:
        if condition_fn(contract_type, data_sensitivity):
            return tier, reason
    return "LOW", "Default — no elevated risk conditions matched"


# ---------------------------------------------------------------------------
# LLM classifier (Claude API — optional)
# ---------------------------------------------------------------------------

def _classify_with_llm(
    aggregated_text: str,
    rule_hints: dict,
    api_key: Optional[str] = None,
) -> Optional[dict]:
    """
    Call claude-opus-4-6 with adaptive thinking and structured JSON output.
    Returns the parsed LLM result dict, or None on any failure.
    Gracefully degrades: missing API key / package → returns None silently.
    """
    if not LLM_AVAILABLE:
        log.warning("'anthropic' package not installed — skipping LLM pass. "
                    "Install with: pip install anthropic")
        return None

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — skipping LLM pass.")
        return None

    # Truncate to stay well within context limits; classification needs ~12k chars max
    MAX_CHARS = 14_000
    text_excerpt = aggregated_text[:MAX_CHARS]
    if len(aggregated_text) > MAX_CHARS:
        log.info(f"Contract text truncated from {len(aggregated_text)} to {MAX_CHARS} chars for LLM call.")

    user_message = (
        f"Rule-based pre-analysis (use as hints only):\n"
        f"{json.dumps(rule_hints, indent=2)}\n\n"
        f"Contract text:\n---\n{text_excerpt}\n---\n\n"
        f"Output schema:\n{json.dumps(LLM_OUTPUT_SCHEMA, indent=2)}"
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        log.info("Calling Claude API (claude-opus-4-6, adaptive thinking, structured output)...")

        # Stream to avoid timeout on large inputs; get_final_message() collects the result
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=LLM_SYSTEM_PROMPT,
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": LLM_OUTPUT_SCHEMA,
                }
            },
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            final = stream.get_final_message()

        # Extract the text block (thinking blocks are separate and ignored here)
        text_block = next(
            (b.text for b in final.content if hasattr(b, "text") and b.type == "text"),
            None,
        )
        if not text_block:
            log.error("LLM returned no text content — using rule-based result.")
            return None

        result = json.loads(text_block)
        log.info(
            f"LLM result: type={result.get('contract_type')}  "
            f"risk={result.get('vendor_risk_tier')}  "
            f"sensitivity={result.get('data_sensitivity')}  "
            f"conf={result.get('confidence', 0):.2f}"
        )
        return result

    except anthropic.AuthenticationError:
        log.error("Invalid ANTHROPIC_API_KEY — skipping LLM pass.")
        return None
    except anthropic.RateLimitError:
        log.warning("Rate limit reached — falling back to rule-based classification.")
        return None
    except anthropic.BadRequestError as e:
        log.error(f"Bad request to Claude API: {e} — skipping LLM pass.")
        return None
    except Exception as e:
        log.error(f"LLM classification failed ({type(e).__name__}: {e}) — using rule-based result.")
        return None


# ---------------------------------------------------------------------------
# Result merger
# ---------------------------------------------------------------------------

def _merge(rule: dict, llm: Optional[dict]) -> dict:
    """
    Deterministic merge strategy:
    - LLM dominates for contract_type, vendor_risk_tier, data_sensitivity
      when llm.confidence >= 0.75, otherwise rule-based result is used.
    - Regulatory scope is NOT part of this merge — it is owned by org_profile.json.
    """
    LLM_CONFIDENCE_THRESHOLD = 0.75

    if llm and llm.get("confidence", 0.0) >= LLM_CONFIDENCE_THRESHOLD:
        contract_type    = llm["contract_type"]
        vendor_risk_tier = llm["vendor_risk_tier"]
        data_sensitivity = llm["data_sensitivity"]
        confidence       = llm["confidence"]
        source           = "LLM+RULES"
    else:
        contract_type    = rule["contract_type"]
        vendor_risk_tier = rule["vendor_risk_tier"]
        data_sensitivity = rule["data_sensitivity"]
        confidence       = rule["confidence"]
        source           = "RULES_ONLY"
        if llm:
            log.warning(
                f"LLM confidence {llm.get('confidence', 0):.2f} < {LLM_CONFIDENCE_THRESHOLD} "
                f"— rule-based result takes precedence."
            )

    return {
        "contract_type":    contract_type,
        "vendor_risk_tier": vendor_risk_tier,
        "data_sensitivity": data_sensitivity,
        "confidence":       round(confidence, 4),
        "_source":          source,
        "_llm_reasoning":   (llm.get("reasoning", "") if llm else ""),
    }


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _load_chunks(path: str) -> list[dict]:
    """Accept either a bare JSON array or {"chunks": [...]} envelope."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "chunks" in data:
        return data["chunks"]
    raise ValueError(
        "contract_chunks.json must be a JSON array or an object with a 'chunks' key."
    )


def _aggregate_text(chunks: list[dict]) -> str:
    parts = [
        chunk.get("text") or chunk.get("content") or ""
        for chunk in chunks
    ]
    return "\n\n".join(filter(None, parts))


def _build_reasoning_signals(signals: dict[str, list[str]], llm_reasoning: str) -> list[str]:
    out = []
    for category, hits in sorted(signals.items()):
        if hits:
            out.append(f"[{category}] keyword hits: {', '.join(hits[:6])}")
    if llm_reasoning:
        out.append(f"[LLM_REASONING] {llm_reasoning[:400]}")
    return out


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(
    input_path: str,
    contract_id: str,
    output_path: str,
    skip_llm: bool,
    api_key: Optional[str] = None,
) -> dict:
    # 1. Load and aggregate
    log.info(f"Loading chunks from: {input_path}")
    chunks = _load_chunks(input_path)
    log.info(f"Loaded {len(chunks)} chunks")
    aggregated_text = _aggregate_text(chunks)
    log.info(f"Aggregated text: {len(aggregated_text)} characters")

    # 2. Rule-based pass
    log.info("Running rule-based classification pass...")
    contract_type_rb, confidence_rb, type_signals = _classify_contract_type(aggregated_text)
    data_sensitivity_rb, sens_signals             = _classify_data_sensitivity(aggregated_text)
    vendor_risk_tier_rb, risk_reason              = _resolve_vendor_risk_tier(
        contract_type_rb, data_sensitivity_rb
    )

    log.info(
        f"Rule-based: type={contract_type_rb}  risk={vendor_risk_tier_rb}  "
        f"sensitivity={data_sensitivity_rb}  conf={confidence_rb}"
    )

    rule_result = {
        "contract_type":    contract_type_rb,
        "vendor_risk_tier": vendor_risk_tier_rb,
        "data_sensitivity": data_sensitivity_rb,
        "confidence":       confidence_rb,
    }
    all_signals: dict[str, list[str]] = {**type_signals, **sens_signals}

    # 3. LLM pass
    llm_result = None
    if not skip_llm:
        rule_hints = {
            "contract_type_hint":    contract_type_rb,
            "data_sensitivity_hint": data_sensitivity_rb,
            "vendor_risk_tier_hint": vendor_risk_tier_rb,
            "keyword_signals":       {k: v[:4] for k, v in all_signals.items() if v},
        }
        llm_result = _classify_with_llm(aggregated_text, rule_hints, api_key=api_key)
    else:
        log.info("LLM pass skipped (--no-llm)")

    # 4. Merge
    merged = _merge(rule_result, llm_result)

    # 5. Build output
    # regulatory_scope is intentionally absent — Stage 5 loads it from org_profile.json
    reasoning_signals = _build_reasoning_signals(all_signals, merged["_llm_reasoning"])

    output = {
        # ---- Public schema (Stage 5 reads these three fields) ----
        "contract_id":      contract_id,
        "contract_type":    merged["contract_type"],
        "vendor_risk_tier": merged["vendor_risk_tier"],
        "data_sensitivity": merged["data_sensitivity"],
        "confidence":       merged["confidence"],
        # ---- Internal metadata (pipeline diagnostics) ----
        "_meta": {
            "classification_source": merged["_source"],
            "chunks_processed":      len(chunks),
            "text_length_chars":     len(aggregated_text),
            "risk_tier_reason":      risk_reason,
            "rule_based_result":     rule_result,
            "llm_result":            llm_result,
            "reasoning_signals":     reasoning_signals,
        },
    }

    # 6. Write
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log.info(f"Output written to: {output_path}")

    return output


def _print_summary(result: dict) -> None:
    RISK_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
    TYPE_ICON = {
        "SAAS": "☁ ", "CLOUD_HOSTING": "🖥", "MSP": "🔧",
        "DATA_PROCESSING": "📋", "ICT_OUTSOURCING": "🏦", "OTHER": "❓",
    }
    meta = result.get("_meta", {})

    print(f"\n{'='*58}")
    print(f"  Contract Classification Engine — Stage 3")
    print(f"{'='*58}")
    print(f"  Contract ID       : {result['contract_id']}")
    print(f"  Contract Type     : {TYPE_ICON.get(result['contract_type'], '')} {result['contract_type']}")
    print(f"  Vendor Risk Tier  : {RISK_ICON.get(result['vendor_risk_tier'], '')} {result['vendor_risk_tier']}")
    print(f"  Data Sensitivity  : {result['data_sensitivity']}")
    print(f"  Regulatory Scope  : [loaded from org_profile.json by Stage 5]")
    print(f"  Confidence        : {result['confidence']:.2f}")
    print(f"  Classification    : {meta.get('classification_source', 'N/A')}")
    print(f"  Chunks Processed  : {meta.get('chunks_processed', 0)}")
    print(f"{'='*58}\n")

    signals = meta.get("reasoning_signals", [])
    if signals:
        print("  Classification signals:")
        for sig in signals[:10]:
            print(f"    • {sig}")
        print()

    risk_reason = meta.get("risk_tier_reason", "")
    if risk_reason:
        print(f"  Risk tier rationale: {risk_reason}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 3 — Contract Classification Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input_file",       help="Path to contract_chunks.json")
    parser.add_argument("--contract-id",    default="CT-2026-001", help="Contract identifier")
    parser.add_argument("--output",         default="contract_metadata.json", help="Output file path")
    parser.add_argument("--no-llm",         action="store_true", help="Skip LLM pass")
    args = parser.parse_args()

    result = run(
        input_path=args.input_file,
        contract_id=args.contract_id,
        output_path=args.output,
        skip_llm=args.no_llm,
    )
    _print_summary(result)


if __name__ == "__main__":
    main()
