#!/usr/bin/env python3
"""
Stage 8: Remediation Proposal Generator

For every HIGH or MEDIUM finding in the compliance pipeline, proposes:
  - problem_summary      — concise description of the legal/operational issue
  - negotiation_guidance — how the provider should address this with the customer
  - suggested_clause     — concrete replacement contractual wording
  - fallback_option      — minimum acceptable compromise if suggested_clause is rejected

Two-pass architecture:
  Pass 1 — Rule-based templates (per finding_type, always runs)
  Pass 2 — LLM refinement via provider abstraction (optional, --no-llm to skip)
             Supports Anthropic (claude-opus-4-6) and OpenAI (gpt-4o).
             LLM result replaces rule result when confidence >= 0.80.

Input files:
  --compliance   stage6_compliance_CT-2026-001.json  (Stage 6 output)
  --obligations  stage4_5_obligation_analysis.json   (Stage 4.5 output)
  --clauses      stage4_clauses.json                 (optional, supplies original text)

Output:
  stage8_remediation_proposals.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Bootstrap project root so 'llm.*' is importable regardless of CWD
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ---------------------------------------------------------------------------
# LLM module imports (graceful degradation)
# ---------------------------------------------------------------------------

try:
    from llm.base import BaseLLMProvider, LLMAuditMetadata, DETERMINISTIC_AI_META
    from llm.prompts import (
        REMEDIATION_SYSTEM_PROMPT,
        REMEDIATION_OUTPUT_SCHEMA,
        PROMPT_VERSION_REMEDIATION,
        build_remediation_user_message,
    )
    from llm.tracing import (
        confidence_bucket,
        decision_delta_proposal,
        review_priority_proposal,
        build_remediation_trace,
    )
    LLM_MODULE_AVAILABLE = True
except ImportError:
    LLM_MODULE_AVAILABLE = False
    BaseLLMProvider = None  # type: ignore[assignment, misc]
    DETERMINISTIC_AI_META: dict = {
        "llm_used": False, "provider": None, "model": None,
        "prompt_version": None, "confidence": None,
    }

    # Inline fallbacks — no external deps required
    def confidence_bucket(c):  # type: ignore[misc]
        if c is None: return None
        return "high" if c >= 0.85 else "medium" if c >= 0.60 else "low"

    def decision_delta_proposal(src):  # type: ignore[misc]
        if src == "rule_based": return None
        if src == "hybrid": return "no_change"
        if src == "llm": return "ai_override"
        return None

    def review_priority_proposal(finding_type, conf_bkt, suggested_clause):  # type: ignore[misc]
        if (conf_bkt == "low" or not suggested_clause.strip()
                or finding_type in ("NON_TRANSFERABLE_REGULATION", "OPERATIONAL_RISK")):
            return "HIGH"
        if conf_bkt == "medium":
            return "MEDIUM"
        return "LOW"

    def build_remediation_trace(finding_type, llm_content, source):  # type: ignore[misc]
        return None


# ── 1. Rule-based proposal templates ─────────────────────────────────────────

RULE_TEMPLATES: dict[str, dict[str, str]] = {
    "AMBIGUOUS_REQUIREMENT": {
        "problem_summary": (
            "Die Klausel verwendet vage, nicht messbare Sprache (z.B. 'Best Practices', 'Stand der "
            "Technik', 'angemessene Maßnahmen'), die eine unbestimmte Verpflichtung begründet. "
            "Ohne objektive Kriterien kann die Erfüllung weder überprüft noch rechtlich durchgesetzt werden."
        ),
        "negotiation_guidance": (
            "Den Auftraggeber auffordern, alle unklaren Leistungsmerkmale durch objektiv prüfbare "
            "Kriterien, konkrete Standards oder messbare Kennzahlen zu ersetzen. Sicherheits- und "
            "Compliance-Verpflichtungen müssen messbar sein. Empfehlung: Modell benannter Standards "
            "(z.B. ISO/IEC 27001:2022) mit Zertifizierung als Nachweis. Offene Formulierungen, die "
            "den Umfang ohne Gegenseitigkeit erweitern können, ablehnen."
        ),
        "suggested_clause": (
            "Der Anbieter implementiert und unterhält Informationssicherheitsmaßnahmen gemäß "
            "ISO/IEC 27001:2022. Die Konformität wird durch eine gültige Zertifizierung eines "
            "akkreditierten Drittprüfers oder eine aktuelle, vom CISO unterzeichnete Erklärung "
            "zum Anwendungsbereich (Statement of Applicability) nachgewiesen. Zusätzliche "
            "Sicherheitsanforderungen des Auftraggebers sind vor Inkrafttreten in einem beiderseitig "
            "unterzeichneten Sicherheitsanforderungsplan zu dokumentieren und dürfen keine Verpflichtungen "
            "begründen, die wesentlich über den genannten Standard hinausgehen, ohne entsprechende "
            "Anpassung von Vergütung und Fristen."
        ),
        "fallback_option": (
            "ISO/IEC 27001:2022-Konformität als Ausgangsnorm akzeptieren, mit definiertem "
            "Überprüfungszyklus zur Ergänzung benannter Standards durch schriftliche Einigung."
        ),
    },

    "NON_TRANSFERABLE_REGULATION": {
        "problem_summary": (
            "Die Klausel überträgt eigene gesetzliche Berichts- und Meldepflichten des Auftraggebers "
            "unmittelbar auf den Anbieter. Regulatorische Pflichten aus dem Status des Auftraggebers "
            "als reguliertes Unternehmen (z.B. nach DORA, NIS2, DSGVO) sind nicht delegierbar: das "
            "regulierte Unternehmen bleibt gegenüber der zuständigen Behörde allein verantwortlich. "
            "Eine solche Übertragung ist rechtlich unwirksam und setzt den Anbieter einer undefinierten "
            "Regulierungshaftung aus."
        ),
        "negotiation_guidance": (
            "Jede Klausel ablehnen, die den Anbieter zum primären Verpflichteten gegenüber einer "
            "Regulierungsbehörde im Namen des Auftraggebers macht. Der Anbieter kann operationelle "
            "Unterstützung anbieten (z.B. fristgerechte Meldungen, Bereitstellung von Prüfungsnachweisen, "
            "SIEM-kompatible Protokolle), darf aber keine Berichte an BaFin, BSI, EBA oder andere "
            "Behörden im Namen des Auftraggebers einreichen. Gegenvorschlag: Unterstützungsmodell — "
            "der Auftraggeber behält die Pflicht, der Anbieter verpflichtet sich zu spezifischen, "
            "abgegrenzten Hilfsleistungen in vereinbarten Fristen."
        ),
        "suggested_clause": (
            "Der Auftraggeber bestätigt, dass alle Melde- und Benachrichtigungspflichten gegenüber "
            "zuständigen Aufsichtsbehörden (einschließlich, aber nicht beschränkt auf BaFin, BSI und EBA), "
            "die sich aus seinem Status als reguliertes Unternehmen ergeben, ausschließlich vom "
            "Auftraggeber zu erfüllen sind. Der Anbieter unterstützt den Auftraggeber bei der Erfüllung "
            "dieser Pflichten, indem er: (i) den Auftraggeber über jeden bestätigten Sicherheitsvorfall, "
            "der Auftraggeberdaten wesentlich betrifft, innerhalb von vier (4) Stunden nach interner "
            "Vorfalldeklaration benachrichtigt; (ii) innerhalb von achtundvierzig (48) Stunden einen "
            "detaillierten Vorfallbericht bereitstellt; (iii) Belege, Protokolle und Dokumentation, die "
            "der Auftraggeber für eigene Behördenmeldungen benötigt, in angemessenem Umfang bereitstellt; "
            "und (iv) während einer Behördenuntersuchung einen benannten Ansprechpartner zur Verfügung "
            "stellt. Der Anbieter ist nicht verpflichtet, Berichte direkt an eine Regulierungsbehörde "
            "im Namen des Auftraggebers einzureichen."
        ),
        "fallback_option": (
            "Unterstützungspflicht des Anbieters (Benachrichtigung, Protokolle, benannter "
            "Ansprechpartner) mit ausdrücklichem Hinweis akzeptieren, dass der Auftraggeber "
            "alle primären Meldepflichten gegenüber Behörden trägt."
        ),
    },

    "OPERATIONAL_RISK": {
        "problem_summary": (
            "Die Klausel enthält operativ unrealistische Verpflichtungen — wie Benachrichtigungen "
            "innerhalb von Minuten, uneingeschränkten oder unangekündigten Prüfzugang zu allen Systemen "
            "oder kontinuierliche Echtzeit-Datenfeeds — die nicht zuverlässig erfüllbar sind, ein "
            "unverhältnismäßiges Sicherheitsrisiko schaffen und technisch nicht skalierbar sind."
        ),
        "negotiation_guidance": (
            "Alle undefinierten oder unrealistischen Zeitverpflichtungen durch spezifische, gestufte "
            "SLAs ersetzen. Prüfrechte auf auftraggeberbezogene Systeme beschränken, mit vereinbarten "
            "Zeitfenstern und Vorabankündigung. Anforderungen nach Echtzeit- oder Dauerprotokoll-Feeds "
            "durch periodische Bereitstellung oder abrufbasierten Zugang mit definiertem SLA ersetzen. "
            "Sicherstellen, dass alle Verpflichtungen begrenzt sind — uneingeschränkter Zugang zu "
            "interner Infrastruktur oder Quellcode stellt ein Sicherheitsrisiko dar."
        ),
        "suggested_clause": (
            "Vorfallbenachrichtigung: Der Anbieter benachrichtigt den Auftraggeber über jeden "
            "bestätigten Sicherheitsvorfall, der Auftraggeberdaten wesentlich betrifft, innerhalb "
            "von vier (4) Geschäftsstunden nach interner Vorfalldeklaration. Ein vollständiger "
            "Vorfallbericht wird innerhalb von achtundvierzig (48) Stunden bereitgestellt. "
            "Prüfrechte: Der Auftraggeber oder ein beauftragter unabhängiger Prüfer kann einmal (1) "
            "pro Kalenderjahr eine Compliance-Prüfung mit dreißig (30) Kalendertagen schriftlicher "
            "Vorankündigung, während üblicher Geschäftszeiten, im Einklang mit den Sicherheits"
            "anforderungen des Anbieters durchführen. Der Prüfungsumfang ist auf Systeme zu beschränken, "
            "die direkt mit den vertraglichen Leistungen zusammenhängen. Protokollzugang: Der Anbieter "
            "stellt auf schriftliche Anforderung innerhalb von vierundzwanzig (24) Stunden aggregierte "
            "Sicherheitsereignisprotokolle zu Auftraggeberumgebungen bereit. Kontinuierliches oder "
            "Echtzeit-Streaming interner Sicherheitsdaten ist nicht im Standardleistungsumfang enthalten."
        ),
        "fallback_option": (
            "SLA von 4 Stunden für erste Benachrichtigung mit 48-Stunden-Vollbericht sowie jährliche "
            "Prüfrechte mit 30 Tagen Vorankündigung und definierten Umfangsbeschränkungen akzeptieren."
        ),
    },

    "SCOPE_UNDEFINED": {
        "problem_summary": (
            "Die Klausel verweist auf 'anwendbares Recht', 'einschlägige Vorschriften' oder "
            "'Branchenstandards', ohne konkrete Rechtsinstrumente, Rahmenwerke oder Aufsichtsbehörden "
            "zu benennen. Dies begründet eine offene, unbestimmte Verpflichtung, die sich ohne "
            "beiderseitige Einigung ausdehnen kann."
        ),
        "negotiation_guidance": (
            "Den Auftraggeber verpflichten, alle referenzierten Rechtsinstrumente, Standards und "
            "Rahmenwerke in einem Vertragsanhang aufzulisten. Änderungen an dieser Aufzählung sind "
            "nur mit schriftlicher Zustimmung beider Parteien zulässig, mit mindestens 90 Tagen "
            "Umsetzungsfrist und dem Recht zur Nachverhandlung der Vergütung bei wesentlichen Mehrkosten."
        ),
        "suggested_clause": (
            "Der Anbieter erfüllt die Datenschutz-, Sicherheits- und Resilienzstandards gemäß "
            "Anlage [A] (Anwendbare Regulatorische Rahmenwerke), wie von den Parteien schriftlich "
            "vereinbart und dem Vertrag beigefügt. Erfordert eine Änderung geltender Gesetze oder "
            "Vorschriften eine Anpassung der Anlage [A], teilt der Auftraggeber dies dem Anbieter "
            "spätestens neunzig (90) Tage vor dem Inkrafttreten schriftlich mit. Verursacht die "
            "Anpassung wesentliche Mehrkosten oder operationellen Mehraufwand, verhandeln die Parteien "
            "binnen dreißig (30) Tagen nach Mitteilung in gutem Glauben eine entsprechende Anpassung "
            "der Vergütung und Fristen. Keine Änderung der Anlage [A] tritt ohne beiderseitige "
            "schriftliche Unterzeichnung in Kraft."
        ),
        "fallback_option": (
            "Definierte Liste benannter Rahmenwerke im Vertragstext mit Änderungsklausel akzeptieren, "
            "die 90 Tage Vorankündigung und beiderseitige schriftliche Zustimmung für Ergänzungen erfordert."
        ),
    },

    "CUSTOMER_RESPONSIBILITY": {
        "problem_summary": (
            "Die Klausel überträgt dem Anbieter Verpflichtungen, die nach DSGVO eigene "
            "Controller-Pflichten des Auftraggebers sind — insbesondere die Datenklassifizierung, "
            "Festlegung von Aufbewahrungsfristen, Bestimmung der Rechtsgrundlage sowie die Durchführung "
            "von Datenschutz-Folgenabschätzungen (DSFA). Diese Pflichten sind nicht delegierbar."
        ),
        "negotiation_guidance": (
            "Alle Klauseln ablehnen, die Controller-Verantwortlichkeiten auf den Anbieter übertragen. "
            "Datenklassifizierung, DSFA-Durchführung, Bestimmung der Rechtsgrundlage und Festlegung "
            "der Aufbewahrungsfristen verbleiben beim Auftraggeber. Der Anbieter kann unterstützende "
            "Informationen liefern (z.B. Beschreibung technischer Verarbeitungsvorgänge für eine DSFA), "
            "darf die rechtliche Beurteilung jedoch nicht vornehmen."
        ),
        "suggested_clause": (
            "Der Auftraggeber, handelnd als Verantwortlicher im Sinne von Art. 4 Nr. 7 DSGVO, ist "
            "allein verantwortlich für: (i) Festlegung und Dokumentation der Sensibilitätsklassifizierung "
            "aller im Rahmen dieses Vertrags verarbeiteten personenbezogenen Daten; (ii) Bestimmung der "
            "Rechtsgrundlage für jede Verarbeitungskategorie gemäß Art. 6 DSGVO sowie Dokumentation in "
            "den Verarbeitungsverzeichnissen des Auftraggebers; (iii) Festlegung der Aufbewahrungsfristen "
            "für jede Kategorie von Auftraggeberdaten, die der Anbieter auf schriftliche Weisung "
            "umsetzt; und (iv) Durchführung jeder nach Art. 35 DSGVO erforderlichen Datenschutz-"
            "Folgenabschätzung. Der Anbieter stellt auf schriftliche Anforderung und innerhalb von "
            "fünfzehn (15) Geschäftstagen eine Beschreibung seiner technischen und organisatorischen "
            "Verarbeitungsvorgänge zur Verfügung. Der Anbieter ist nicht verpflichtet, eine DSFA im "
            "Namen des Auftraggebers durchzuführen, zu unterzeichnen oder einzureichen."
        ),
        "fallback_option": (
            "DSFA-Mitwirkungsklausel akzeptieren, nach der der Anbieter innerhalb von 15 "
            "Geschäftstagen Verarbeitungsdetails bereitstellt, während der Auftraggeber "
            "Autor der DSFA bleibt."
        ),
    },
}

INCLUDED_SEVERITIES = {"HIGH", "MEDIUM"}


# ── 2. Loaders ────────────────────────────────────────────────────────────────

def _load_json(path: str, label: str) -> Any:
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] {label} not found: {path}", file=sys.stderr)
        sys.exit(1)
    with p.open() as fh:
        return json.load(fh)


def _build_clause_index(clauses_path: str) -> dict[str, str]:
    """Returns {clause_id -> original_text} if clauses file is available."""
    if not clauses_path:
        return {}
    p = Path(clauses_path)
    if not p.exists():
        print(f"[WARN] clauses file not found: {clauses_path}", file=sys.stderr)
        return {}
    with p.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return {c["clause_id"]: c["text"] for c in data if "clause_id" in c and "text" in c}


# ── 3. Rule-based pass ────────────────────────────────────────────────────────

def _rule_proposal(finding: dict) -> dict:
    ftype = finding.get("finding_type", "")
    tmpl  = RULE_TEMPLATES.get(ftype)
    if not tmpl:
        return {
            "problem_summary":      finding.get("reason", "Kein Regeltemplate verfügbar."),
            "negotiation_guidance": finding.get("recommended_action", "Rechtliche Prüfung empfohlen."),
            "suggested_clause": (
                "Die Parteien verhandeln konkrete, messbare Pflichten als Ersatz für diese Klausel. "
                "Jede Verpflichtung muss: (i) präzise abgegrenzt; (ii) zeitlich befristet; (iii) für "
                "den Dienstleister operativ umsetzbar; und (iv) anhand objektiver Kriterien überprüfbar sein."
            ),
            "fallback_option": (
                "Schriftliche Einigung über einen definierten Umfang und Zeitplan, bevor diese Klausel in Kraft tritt."
            ),
        }
    return {
        "problem_summary":      tmpl["problem_summary"],
        "negotiation_guidance": tmpl["negotiation_guidance"],
        "suggested_clause":     tmpl["suggested_clause"],
        "fallback_option":      tmpl["fallback_option"],
    }


# ── 4. LLM pass ──────────────────────────────────────────────────────────────

LLM_CONFIDENCE_THRESHOLD = 0.80


def _llm_proposal(
    finding:       dict,
    original_text: str,
    rule_proposal: dict,
    provider:      "BaseLLMProvider",
) -> Optional[dict]:
    """
    Call LLM to produce a clause-specific remediation proposal.
    Returns the LLM response dict, or None if the call failed.
    """
    user_msg = build_remediation_user_message(finding, original_text, rule_proposal)

    try:
        response = provider.complete_structured(
            system_prompt  = REMEDIATION_SYSTEM_PROMPT,
            user_message   = user_msg,
            json_schema    = REMEDIATION_OUTPUT_SCHEMA,
            prompt_version = PROMPT_VERSION_REMEDIATION,
            max_tokens     = 1024,
        )
    except RuntimeError as exc:
        print(f"  [LLM WARN] Unrecoverable error for {finding.get('clause_id')}: {exc}",
              file=sys.stderr)
        return None

    return response


# ── 5. Main pipeline ──────────────────────────────────────────────────────────

def extract_findings(compliance_report: dict, obligations: list[dict]) -> list[dict]:
    """
    Merge Stage 6 obligation findings with Stage 4.5 detail.
    Only HIGH and MEDIUM severities pass through.
    """
    ob_index: dict[str, dict] = {c["clause_id"]: c for c in obligations}
    findings: list[dict] = []

    for f in compliance_report.get("obligation_analysis", {}).get("findings", []):
        if f.get("severity") not in INCLUDED_SEVERITIES:
            continue
        ob_detail = ob_index.get(f.get("clause_id", ""), {})
        merged = {**f}
        for key in ("reason", "recommended_action", "_confidence", "_source", "_ai_metadata"):
            if key not in merged and key in ob_detail:
                merged[key] = ob_detail[key]
        findings.append(merged)

    return findings


def generate_proposals(
    findings:     list[dict],
    clause_index: dict[str, str],
    llm_provider: Optional["BaseLLMProvider"] = None,
    verbose:      bool = True,
) -> list[dict]:
    """
    Generate remediation proposals for a list of findings.

    Parameters
    ----------
    findings:     List of compliance findings (HIGH/MEDIUM severity)
    clause_index: {clause_id -> original_text} for LLM context
    llm_provider: Pre-initialised LLM provider (from llm.config.get_llm_provider)
    verbose:      Print per-finding progress
    """
    provider = llm_provider
    proposals: list[dict] = []

    for finding in findings:
        clause_id     = finding.get("clause_id", "unknown")
        ftype         = finding.get("finding_type", "UNKNOWN")
        severity      = finding.get("severity", "MEDIUM")
        original_text = clause_index.get(clause_id, "")

        if verbose:
            print(f"  Processing {clause_id}  [{severity}] {ftype} …", end=" ", flush=True)

        # Pass 1: rule-based
        rule           = _rule_proposal(finding)
        proposal_src   = "rule_based"
        final_proposal = rule
        ai_meta        = DETERMINISTIC_AI_META
        llm_content_raw: Optional[dict] = None

        # Pass 2: LLM (optional)
        if provider is not None and LLM_MODULE_AVAILABLE:
            llm_resp = _llm_proposal(finding, original_text, rule, provider)
            if llm_resp is not None:
                llm_content_raw = llm_resp.content
                llm_conf        = llm_content_raw.get("confidence", 0.0)
                if llm_conf >= LLM_CONFIDENCE_THRESHOLD:
                    final_proposal = {
                        "problem_summary":      llm_content_raw["problem_summary"],
                        "negotiation_guidance": llm_content_raw["negotiation_guidance"],
                        "suggested_clause":     llm_content_raw["suggested_clause"],
                        "fallback_option":      llm_content_raw.get("fallback_option", rule["fallback_option"]),
                    }
                    proposal_src = "llm"
                    ai_meta      = llm_resp.metadata.to_dict()
                else:
                    # LLM low confidence — keep rule base but record hybrid attempt
                    proposal_src = "hybrid"
                    ai_meta      = llm_resp.metadata.to_dict()

        if verbose:
            print(proposal_src)

        # ── Explainability fields ──────────────────────────────────────────
        ai_attempted  = (proposal_src != "rule_based")
        ai_conf       = ai_meta.get("confidence") if ai_attempted else None
        conf_bkt      = confidence_bucket(ai_conf)
        baseline      = {
            "problem_summary_preview":  rule["problem_summary"][:120],
            "suggested_clause_preview": rule["suggested_clause"][:120],
        } if ai_attempted else None
        delta         = decision_delta_proposal(proposal_src)
        priority      = review_priority_proposal(
            ftype, conf_bkt, final_proposal.get("suggested_clause", "")
        )
        trace         = build_remediation_trace(ftype, llm_content_raw, proposal_src)

        proposals.append({
            "clause_id":              clause_id,
            "finding_type":           ftype,
            "severity":               severity,
            "page":                   finding.get("page"),
            "layout_type":            finding.get("layout_type"),
            "original_text_preview":  (original_text[:200] + "…") if len(original_text) > 200 else original_text,
            "problem_summary":        final_proposal["problem_summary"],
            "negotiation_guidance":   final_proposal["negotiation_guidance"],
            "suggested_clause":       final_proposal["suggested_clause"],
            "fallback_option":        final_proposal.get("fallback_option", ""),
            "_proposal_source":       proposal_src,
            "_ai_metadata":           ai_meta,
            "_baseline_result":       baseline,
            "_decision_delta":        delta,
            "_confidence_bucket":     conf_bkt,
            "_review_priority":       priority,
            "_ai_trace":              trace,
        })

    return proposals


# ── 6. Terminal summary ───────────────────────────────────────────────────────

_SEV_ICON = {"HIGH": "🔴", "MEDIUM": "🟡"}
_W = 72


def print_summary(proposals: list[dict], output_path: str) -> None:
    sep  = "─" * _W
    high = [p for p in proposals if p["severity"] == "HIGH"]
    med  = [p for p in proposals if p["severity"] == "MEDIUM"]
    llm_used = sum(1 for p in proposals
                   if p.get("_ai_metadata", {}).get("llm_used", False))

    print(f"\n{'═' * _W}")
    print(f"  STAGE 8 — REMEDIATION PROPOSALS")
    print(f"{'═' * _W}")
    print(f"  Generated : {len(proposals)} proposals  "
          f"│  HIGH={len(high)}  MEDIUM={len(med)}")
    print(f"  LLM-enhanced: {llm_used} / {len(proposals)}")
    print(sep)

    for p in proposals:
        icon = _SEV_ICON.get(p["severity"], "❓")
        src  = "🤖" if p.get("_proposal_source") in ("llm", "hybrid") else "📋"
        print(f"\n  {icon} {p['clause_id']}  [{p['finding_type']}]  "
              f"{src} {p.get('_proposal_source', 'rule_based')}")
        if p.get("page"):
            print(f"     page={p['page']}  layout={p.get('layout_type', 'n/a')}")

        summary = p["problem_summary"]
        print(f"     Problem  : {summary[:66]}")
        if len(summary) > 66:
            for chunk in [summary[i:i+66] for i in range(66, len(summary), 66)]:
                print(f"               {chunk}")

        clause_preview = p["suggested_clause"][:120].replace("\n", " ") + "…"
        print(f"     Clause   : {clause_preview}")

    print(f"\n{sep}")
    print(f"  Output saved → {output_path}")
    print(f"{'═' * _W}\n")


# ── 7. CLI ────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Stage 8: Generate remediation proposals for flagged contract clauses."
    )
    ap.add_argument("--compliance", "-c", default="stage6_compliance_CT-2026-001.json")
    ap.add_argument("--obligations", "-b", default="stage4_5_obligation_analysis.json")
    ap.add_argument("--clauses", default="stage4_clauses.json")
    ap.add_argument("--output", "-o", default="stage8_remediation_proposals.json")
    ap.add_argument("--no-llm", dest="no_llm", action="store_true",
                    help="Skip LLM pass; use rule-based templates only")
    ap.add_argument("--quiet", "-q", action="store_true")
    return ap.parse_args()


def main() -> None:
    args = _parse_args()

    compliance   = _load_json(args.compliance,  "compliance report")
    obligations  = _load_json(args.obligations, "obligation analysis")
    clause_index = _build_clause_index(args.clauses)

    provider = None
    if not args.no_llm and LLM_MODULE_AVAILABLE:
        try:
            from llm.config import get_llm_provider
            provider = get_llm_provider()
        except Exception as exc:
            print(f"[WARN] LLM unavailable ({exc}); falling back to rule-based.", file=sys.stderr)

    findings = extract_findings(compliance, obligations)
    if not args.quiet:
        print(f"\n  Stage 8 — processing {len(findings)} findings "
              f"(HIGH={sum(1 for f in findings if f['severity']=='HIGH')}, "
              f"MEDIUM={sum(1 for f in findings if f['severity']=='MEDIUM')}) …")

    proposals = generate_proposals(
        findings      = findings,
        clause_index  = clause_index,
        llm_provider  = provider,
        verbose       = not args.quiet,
    )

    with open(args.output, "w") as fh:
        json.dump(proposals, fh, indent=2)

    if not args.quiet:
        print_summary(proposals, args.output)


if __name__ == "__main__":
    main()
