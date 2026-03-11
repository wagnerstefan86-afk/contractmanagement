"""
Stage 5: Clause-to-Requirement Matching and Gap Detection.

Pipeline:
  1. normalize_clauses()        — LLM: clause_text → normalized_clause
  2. embed_clauses()            — API: normalized_clause → normalized_embedding
  3. retrieve_candidates()      — SQL: cosine search against requirement_embedding
  4. run_llm_validation()       — LLM: semantic coverage assessment per candidate
  5. compute_match_confidence() — arithmetic: weighted composite score
  6. select_best_matches()      — pick winning clause per sub_requirement
  7. promote_to_findings()      — write winning matches + gaps to findings table
  8. detect_gaps()              — mandatory sub_requirements with no full/partial match

Entry point: run_stage5(session, contract_id, llm_client, embedding_client)

LLM model: claude-haiku-4-5 (normalization + matching validation).
Embedding model: text-embedding-3-small (1536 dimensions, cl100k_base tokenizer).
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from pipeline.prompts.stage5_prompts import (
    MATCHING_REQUIRED_KEYS,
    NORMALIZATION_REQUIRED_KEYS,
    VALID_COVERAGE_VALUES,
    build_matching_messages,
    build_normalization_messages,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CANDIDATE_LIMIT         = 10     # top-N candidates per clause from embedding search
EMBEDDING_PASS1_CUTOFF  = 0.40   # minimum embedding_similarity to proceed to Pass 2
LLM_MODEL               = "claude-haiku-4-5-20251001"
LLM_PROMPT_VERSION      = "stage5_v1.0"
EMBEDDING_MODEL         = "text-embedding-3-small"
EMBEDDING_BATCH_SIZE    = 100

# Quality band → numeric score for confidence formula
_QUALITY_BAND_SCORES: dict[str, float] = {
    "STRONG":     1.00,
    "ADEQUATE":   0.75,
    "WEAK":       0.50,
    "INADEQUATE": 0.25,
    "NOMINAL":    0.10,
}

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class CandidateRow:
    sub_requirement_id:          str
    framework_id:                str
    framework_name:              str
    description:                 str
    evidence_keywords:           list[str]
    missing_severity:            str
    missing_finding_template:    Optional[str]
    mandatory:                   bool
    min_quality_score:           float
    weight:                      float
    embedding_similarity:        float


@dataclass
class MatchResult:
    clause_id:           uuid.UUID
    sub_requirement_id:  str
    framework_id:        str
    embedding_similarity: float
    requirement_match:   bool
    llm_confidence:      float
    coverage:            str            # 'full' | 'partial' | 'none'
    explanation:         str
    missing_elements:    list[str]
    match_confidence:    float


# ---------------------------------------------------------------------------
# Step 1: Clause normalization
# ---------------------------------------------------------------------------

def normalize_clauses(
    session: Session,
    contract_id: uuid.UUID,
    llm_client: Any,
) -> None:
    """Populate clauses.normalized_clause for all clauses in the contract.

    Skips clauses that already have a non-NULL normalized_clause value
    (idempotent restart support).
    """
    rows = session.execute(
        text("""
            SELECT c.id, c.clause_text, c.section_reference,
                   c.primary_category::text
            FROM clauses c
            WHERE c.contract_id = :cid
              AND c.normalized_clause IS NULL
            ORDER BY c.created_at
        """),
        {"cid": str(contract_id)},
    ).fetchall()

    if not rows:
        log.info("normalize_clauses: all clauses already normalized, skipping")
        return

    log.info("normalize_clauses: normalizing %d clauses", len(rows))

    for row in rows:
        clause_id, clause_text, section_ref, primary_cat = row

        system, user = build_normalization_messages(
            clause_text=clause_text,
            primary_category=primary_cat,
            section_reference=section_ref,
        )

        try:
            parsed = _call_llm_json(llm_client, system, user, NORMALIZATION_REQUIRED_KEYS)
        except ValueError as exc:
            log.warning("normalize_clauses: clause %s failed — %s", clause_id, exc)
            # Write empty string so we don't retry indefinitely on restart
            parsed = {"normalized_clause": ""}

        session.execute(
            text("""
                UPDATE clauses
                SET normalized_clause = :nc
                WHERE id = :cid
            """),
            {"nc": parsed["normalized_clause"], "cid": str(clause_id)},
        )

    session.commit()
    log.info("normalize_clauses: committed %d normalizations", len(rows))


# ---------------------------------------------------------------------------
# Step 2: Embed normalized clauses
# ---------------------------------------------------------------------------

def embed_clauses(
    session: Session,
    contract_id: uuid.UUID,
    embedding_client: Any,
) -> None:
    """Compute normalized_embedding for clauses that have a normalized_clause
    but no normalized_embedding yet. Batches in groups of EMBEDDING_BATCH_SIZE.
    """
    rows = session.execute(
        text("""
            SELECT id, normalized_clause
            FROM clauses
            WHERE contract_id   = :cid
              AND normalized_clause IS NOT NULL
              AND normalized_clause != ''
              AND normalized_embedding IS NULL
            ORDER BY created_at
        """),
        {"cid": str(contract_id)},
    ).fetchall()

    if not rows:
        return

    log.info("embed_clauses: embedding %d normalized clauses", len(rows))

    for batch_start in range(0, len(rows), EMBEDDING_BATCH_SIZE):
        batch = rows[batch_start: batch_start + EMBEDDING_BATCH_SIZE]
        texts = [r[1] for r in batch]
        ids   = [r[0] for r in batch]

        vectors = _batch_embed(embedding_client, texts)

        for clause_id, vector in zip(ids, vectors):
            session.execute(
                text("""
                    UPDATE clauses
                    SET normalized_embedding = :vec,
                        updated_at           = NOW()
                    WHERE id = :cid
                """),
                {"vec": str(vector), "cid": str(clause_id)},
            )

    session.commit()
    log.info("embed_clauses: committed %d embeddings", len(rows))


# ---------------------------------------------------------------------------
# Step 3: Candidate retrieval
# ---------------------------------------------------------------------------

_CANDIDATE_SQL = text("""
    -- For a single clause (parameterised by :clause_embedding vector and
    -- :contract_type text), retrieve the top-:limit sub_requirements ordered
    -- by cosine distance to the clause's normalized_embedding.
    --
    -- Filters to sub_requirements that are mapped to the contract type
    -- (mandatory OR optional) and whose requirement_embedding is computed.
    --
    -- Returns embedding_similarity = 1 - cosine_distance so that higher
    -- values mean closer match (consistent with the match_confidence formula).
    SELECT
        sr.id                                                         AS sub_requirement_id,
        d.framework_id                                                AS framework_id,
        f.name                                                        AS framework_name,
        sr.description                                                AS description,
        sr.evidence_keywords                                          AS evidence_keywords,
        sr.missing_severity::text                                     AS missing_severity,
        sr.missing_finding_template                                   AS missing_finding_template,
        ctm.mandatory                                                 AS mandatory,
        ctm.min_quality_score                                         AS min_quality_score,
        ctm.weight                                                    AS weight,
        1 - (sr.requirement_embedding <=> :clause_embedding::vector)  AS embedding_similarity
    FROM sub_requirements sr
    JOIN requirements   r   ON r.id  = sr.requirement_id
    JOIN domains        d   ON d.id  = r.domain_id
    JOIN frameworks     f   ON f.id  = d.framework_id
    JOIN contract_type_req_mapping ctm
        ON  ctm.sub_requirement_id = sr.id
        AND ctm.contract_type      = :contract_type
    WHERE sr.requirement_embedding IS NOT NULL
    ORDER BY sr.requirement_embedding <=> :clause_embedding::vector
    LIMIT :lim
""")


def retrieve_candidates(
    session: Session,
    clause_embedding: list[float],
    contract_type: str,
    limit: int = CANDIDATE_LIMIT,
) -> list[CandidateRow]:
    """Return the top-N sub_requirements closest to clause_embedding.

    Args:
        clause_embedding: normalized_embedding as a Python float list.
        contract_type:    contract_type_enum value string (e.g. 'saas').
        limit:            maximum number of candidates to return.
    """
    # pgvector expects the literal '[1.0,0.5,...]' string representation
    vec_str = "[" + ",".join(f"{v:.8f}" for v in clause_embedding) + "]"

    rows = session.execute(
        _CANDIDATE_SQL,
        {"clause_embedding": vec_str, "contract_type": contract_type, "lim": limit},
    ).fetchall()

    candidates = []
    for row in rows:
        sim = float(row.embedding_similarity)
        if sim < EMBEDDING_PASS1_CUTOFF:
            continue  # below threshold — skip Pass 2 entirely
        candidates.append(CandidateRow(
            sub_requirement_id=row.sub_requirement_id,
            framework_id=row.framework_id,
            framework_name=row.framework_name,
            description=row.description,
            evidence_keywords=list(row.evidence_keywords or []),
            missing_severity=row.missing_severity,
            missing_finding_template=row.missing_finding_template,
            mandatory=bool(row.mandatory),
            min_quality_score=float(row.min_quality_score),
            weight=float(row.weight),
            embedding_similarity=sim,
        ))

    return candidates


# ---------------------------------------------------------------------------
# Step 4: LLM semantic validation
# ---------------------------------------------------------------------------

def run_llm_validation(
    clause_id: uuid.UUID,
    clause_text: str,
    normalized_clause: Optional[str],
    section_reference: Optional[str],
    language_strength: float,
    quality_band: str,
    modifier_types: list[str],
    candidate: CandidateRow,
    llm_client: Any,
) -> dict:
    """Call the LLM to assess coverage for one (clause, sub_requirement) pair.

    Returns the parsed JSON dict with keys defined in MATCHING_REQUIRED_KEYS.
    Raises ValueError on parse failure (caller handles retry / fallback).
    """
    system, user = build_matching_messages(
        clause_text=clause_text,
        normalized_clause=normalized_clause,
        section_reference=section_reference,
        sub_requirement_id=candidate.sub_requirement_id,
        sub_requirement_description=candidate.description,
        framework_id=candidate.framework_id,
        framework_name=candidate.framework_name,
        evidence_keywords=candidate.evidence_keywords,
        embedding_similarity=candidate.embedding_similarity,
        language_strength=language_strength,
        quality_band=quality_band,
        modifier_types=modifier_types,
    )
    parsed = _call_llm_json(llm_client, system, user, MATCHING_REQUIRED_KEYS)

    if parsed["coverage"] not in VALID_COVERAGE_VALUES:
        raise ValueError(f"Invalid coverage value: {parsed['coverage']!r}")

    # Ensure requirement_match is consistent with coverage
    if parsed["coverage"] == "none":
        parsed["requirement_match"] = False
    elif parsed["coverage"] in ("full", "partial"):
        parsed["requirement_match"] = True

    return parsed


# ---------------------------------------------------------------------------
# Step 5: Composite match confidence
# ---------------------------------------------------------------------------

def compute_match_confidence(
    embedding_similarity: float,
    llm_confidence: float,
    quality_band: str,
) -> float:
    """Return match_confidence in [0, 1].

    Formula:
        match_confidence = 0.35 * embedding_similarity
                         + 0.45 * llm_confidence
                         + 0.20 * quality_band_score

    Weights reflect that LLM validation is the primary signal (0.45),
    embedding similarity is a strong secondary signal (0.35), and clause
    quality adjusts the score to penalise weak/nominal clauses (0.20).

    quality_band_score mapping:
        STRONG:     1.00
        ADEQUATE:   0.75
        WEAK:       0.50
        INADEQUATE: 0.25
        NOMINAL:    0.10
    """
    quality_score = _QUALITY_BAND_SCORES.get(quality_band.upper(), 0.50)
    raw = (
        0.35 * embedding_similarity
        + 0.45 * llm_confidence
        + 0.20 * quality_score
    )
    return round(min(max(raw, 0.0), 1.0), 4)


# ---------------------------------------------------------------------------
# Step 6 + 7: Persist matches and select best
# ---------------------------------------------------------------------------

def _write_match_row(
    session: Session,
    contract_id: uuid.UUID,
    clause_id: uuid.UUID,
    candidate: CandidateRow,
    llm_result: dict,
    match_confidence: float,
) -> uuid.UUID:
    """Insert one row into clause_requirement_matches. Returns new row id."""
    row_id = uuid.uuid4()
    session.execute(
        text("""
            INSERT INTO clause_requirement_matches (
                id, contract_id, clause_id, sub_requirement_id, framework_id,
                embedding_similarity,
                llm_validated, llm_confidence, coverage, explanation, missing_elements,
                match_confidence, is_best_match,
                llm_model_used, llm_prompt_version
            ) VALUES (
                :id, :contract_id, :clause_id, :sub_req_id, :fw_id,
                :emb_sim,
                :llm_validated, :llm_conf, :coverage, :explanation, :missing_elements,
                :match_conf, FALSE,
                :llm_model, :prompt_ver
            )
        """),
        {
            "id":               str(row_id),
            "contract_id":      str(contract_id),
            "clause_id":        str(clause_id),
            "sub_req_id":       candidate.sub_requirement_id,
            "fw_id":            candidate.framework_id,
            "emb_sim":          candidate.embedding_similarity,
            "llm_validated":    llm_result.get("requirement_match"),
            "llm_conf":         llm_result.get("confidence"),
            "coverage":         llm_result.get("coverage"),
            "explanation":      llm_result.get("explanation"),
            "missing_elements": llm_result.get("missing_elements", []),
            "match_conf":       match_confidence,
            "llm_model":        LLM_MODEL,
            "prompt_ver":       LLM_PROMPT_VERSION,
        },
    )
    return row_id


def select_best_matches(session: Session, contract_id: uuid.UUID) -> None:
    """Mark is_best_match = TRUE for the highest match_confidence row per
    (contract_id, sub_requirement_id), among rows where coverage != 'none'.

    Runs as a single UPDATE with a window function — no Python iteration needed.
    """
    session.execute(
        text("""
            UPDATE clause_requirement_matches AS crm
            SET is_best_match = TRUE
            FROM (
                SELECT DISTINCT ON (contract_id, sub_requirement_id)
                    id
                FROM clause_requirement_matches
                WHERE contract_id = :cid
                  AND coverage    != 'none'
                ORDER BY
                    contract_id,
                    sub_requirement_id,
                    match_confidence DESC NULLS LAST,
                    embedding_similarity DESC
            ) AS best
            WHERE crm.id = best.id
        """),
        {"cid": str(contract_id)},
    )
    session.commit()


# ---------------------------------------------------------------------------
# Step 8: Gap detection → findings
# ---------------------------------------------------------------------------

_GAP_SQL = text("""
    -- Sub-requirements that are mandatory for this contract type AND have
    -- no best-match row with coverage in ('full', 'partial').
    SELECT
        sr.id                       AS sub_requirement_id,
        d.framework_id              AS framework_id,
        sr.missing_severity::text   AS missing_severity,
        sr.missing_finding_template AS missing_finding_template,
        sr.name                     AS name
    FROM contract_type_req_mapping ctm
    JOIN sub_requirements sr ON sr.id  = ctm.sub_requirement_id
    JOIN requirements     r  ON r.id   = sr.requirement_id
    JOIN domains          d  ON d.id   = r.domain_id
    WHERE ctm.contract_type = :contract_type
      AND ctm.mandatory     = TRUE
      AND sr.id NOT IN (
          SELECT sub_requirement_id
          FROM   clause_requirement_matches
          WHERE  contract_id = :cid
            AND  is_best_match = TRUE
            AND  coverage IN ('full', 'partial')
      )
""")


def detect_gaps(
    session: Session,
    contract_id: uuid.UUID,
    contract_type: str,
) -> list[dict]:
    """Return a list of gap findings for mandatory sub_requirements with no
    clause coverage. Each dict is ready for insertion into the findings table.
    """
    rows = session.execute(
        _GAP_SQL,
        {"cid": str(contract_id), "contract_type": contract_type},
    ).fetchall()

    gaps = []
    for row in rows:
        template = row.missing_finding_template or (
            f"No clause addressing '{row.name}' was found in the contract."
        )
        gaps.append({
            "contract_id":         str(contract_id),
            "clause_id":           None,
            "framework_id":        row.framework_id,
            "sub_requirement_id":  row.sub_requirement_id,
            "finding_type":        "missing",
            "severity":            row.missing_severity,
            "confidence":          1.000,          # absence is certain
            "justification":       template,
            "recommendation":      (
                f"Add a clause explicitly addressing the '{row.name}' requirement "
                f"under framework {row.framework_id}."
            ),
            "clause_risk_score":   100.00,
            "clause_quality_score": None,
            "clause_quality_band":  None,
            "post_modifier_quality": None,
            "llm_model_used":       None,
            "llm_prompt_version":   None,
        })

    return gaps


def promote_to_findings(
    session: Session,
    contract_id: uuid.UUID,
    llm_prompt_version: str = LLM_PROMPT_VERSION,
) -> int:
    """Insert best-match rows as findings. Returns the number of rows inserted.

    Maps coverage → finding_type:
        full    → present
        partial → partial
        (none-coverage rows are never best_match, so they don't reach here)

    Skips sub_requirements that already have a finding for this contract
    (idempotency: safe to call multiple times).
    """
    rows = session.execute(
        text("""
            SELECT
                crm.clause_id,
                crm.sub_requirement_id,
                crm.framework_id,
                crm.coverage,
                crm.llm_confidence,
                crm.explanation,
                crm.missing_elements,
                crm.match_confidence,
                cqs.raw_quality_score,
                cqs.quality_band,
                -- post_modifier_quality: raw_quality * product of penalty multipliers
                cqs.raw_quality_score * COALESCE(
                    (SELECT EXP(SUM(LN(penalty_multiplier)))
                     FROM clause_modifiers
                     WHERE clause_id = crm.clause_id),
                    1.0
                ) AS post_modifier_quality
            FROM clause_requirement_matches crm
            JOIN clauses              cl  ON cl.id  = crm.clause_id
            LEFT JOIN clause_quality_scores cqs ON cqs.clause_id = crm.clause_id
            WHERE crm.contract_id  = :cid
              AND crm.is_best_match = TRUE
              AND crm.coverage     IN ('full', 'partial')
              AND NOT EXISTS (
                  SELECT 1 FROM findings f
                  WHERE f.contract_id        = crm.contract_id
                    AND f.sub_requirement_id = crm.sub_requirement_id
                    AND f.finding_type      != 'missing'
              )
        """),
        {"cid": str(contract_id)},
    ).fetchall()

    _COVERAGE_TO_FINDING = {"full": "present", "partial": "partial"}

    for row in rows:
        raw_quality       = float(row.raw_quality_score)  if row.raw_quality_score   else None
        post_modifier     = float(row.post_modifier_quality) if row.post_modifier_quality else None
        clause_risk       = round(100.0 * (1.0 - (post_modifier or raw_quality or 0.0)), 2)
        finding_type      = _COVERAGE_TO_FINDING[row.coverage]
        severity          = _risk_to_severity(clause_risk)
        recommendation    = (
            _format_partial_recommendation(row.missing_elements)
            if finding_type == "partial"
            else "No action required — clause fully satisfies this sub-requirement."
        )

        session.execute(
            text("""
                INSERT INTO findings (
                    id, contract_id, clause_id, framework_id, sub_requirement_id,
                    finding_type, severity, confidence,
                    justification, recommendation,
                    clause_risk_score, clause_quality_score, clause_quality_band,
                    post_modifier_quality, llm_model_used, llm_prompt_version
                ) VALUES (
                    uuid_generate_v4(),
                    :contract_id, :clause_id, :framework_id, :sub_req_id,
                    :finding_type, :severity, :confidence,
                    :justification, :recommendation,
                    :clause_risk, :quality_score, :quality_band,
                    :post_modifier, :llm_model, :prompt_ver
                )
            """),
            {
                "contract_id":   str(contract_id),
                "clause_id":     str(row.clause_id),
                "framework_id":  row.framework_id,
                "sub_req_id":    row.sub_requirement_id,
                "finding_type":  finding_type,
                "severity":      severity,
                "confidence":    row.match_confidence or row.llm_confidence or 0.5,
                "justification": row.explanation,
                "recommendation": recommendation,
                "clause_risk":   clause_risk,
                "quality_score": raw_quality,
                "quality_band":  row.quality_band,
                "post_modifier": post_modifier,
                "llm_model":     LLM_MODEL,
                "prompt_ver":    llm_prompt_version,
            },
        )

    session.commit()
    return len(rows)


def insert_gap_findings(session: Session, gaps: list[dict]) -> None:
    for gap in gaps:
        session.execute(
            text("""
                INSERT INTO findings (
                    id, contract_id, clause_id, framework_id, sub_requirement_id,
                    finding_type, severity, confidence,
                    justification, recommendation,
                    clause_risk_score, clause_quality_score, clause_quality_band,
                    post_modifier_quality, llm_model_used, llm_prompt_version
                ) VALUES (
                    uuid_generate_v4(),
                    :contract_id, NULL, :framework_id, :sub_requirement_id,
                    'missing', :severity, :confidence,
                    :justification, :recommendation,
                    :clause_risk_score, NULL, NULL,
                    NULL, NULL, NULL
                )
                ON CONFLICT DO NOTHING
            """),
            gap,
        )
    session.commit()


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_stage5(
    session: Session,
    contract_id: uuid.UUID,
    contract_type: str,
    llm_client: Any,
    embedding_client: Any,
) -> dict:
    """Run all Stage 5 steps for one contract.

    Returns a summary dict for audit_log.
    """
    log.info("Stage 5 starting for contract %s (type=%s)", contract_id, contract_type)

    # Step 1 — normalize
    normalize_clauses(session, contract_id, llm_client)

    # Step 2 — embed normalized clauses
    embed_clauses(session, contract_id, embedding_client)

    # Load all clauses with their embeddings and quality scores
    clause_rows = session.execute(
        text("""
            SELECT
                c.id,
                c.clause_text,
                c.normalized_clause,
                c.section_reference,
                c.normalized_embedding::text,
                COALESCE(cqs.language_strength, 0.5)   AS language_strength,
                COALESCE(cqs.quality_band, 'ADEQUATE')  AS quality_band,
                ARRAY_REMOVE(
                    ARRAY_AGG(DISTINCT cm.modifier_type::text),
                    NULL
                ) AS modifier_types
            FROM clauses c
            LEFT JOIN clause_quality_scores cqs ON cqs.clause_id = c.id
            LEFT JOIN clause_modifiers      cm  ON cm.clause_id  = c.id
            WHERE c.contract_id          = :cid
              AND c.normalized_embedding IS NOT NULL
            GROUP BY c.id, c.clause_text, c.normalized_clause, c.section_reference,
                     c.normalized_embedding, cqs.language_strength, cqs.quality_band
        """),
        {"cid": str(contract_id)},
    ).fetchall()

    total_candidates   = 0
    total_llm_calls    = 0
    total_llm_failures = 0

    for clause_row in clause_rows:
        clause_id   = clause_row.id
        clause_emb  = _parse_embedding(clause_row.normalized_embedding)
        if not clause_emb:
            continue

        # Step 3 — retrieve candidates
        candidates = retrieve_candidates(session, clause_emb, contract_type)
        total_candidates += len(candidates)

        for candidate in candidates:
            total_llm_calls += 1

            # Step 4 — LLM validation
            try:
                llm_result = run_llm_validation(
                    clause_id=clause_id,
                    clause_text=clause_row.clause_text,
                    normalized_clause=clause_row.normalized_clause,
                    section_reference=clause_row.section_reference,
                    language_strength=float(clause_row.language_strength),
                    quality_band=clause_row.quality_band,
                    modifier_types=list(clause_row.modifier_types or []),
                    candidate=candidate,
                    llm_client=llm_client,
                )
            except ValueError as exc:
                log.warning("Stage 5 LLM validation failed for clause %s / %s: %s",
                            clause_id, candidate.sub_requirement_id, exc)
                total_llm_failures += 1
                # Fallback: record embedding-only result as 'none' coverage
                llm_result = {
                    "requirement_match": False,
                    "confidence":        candidate.embedding_similarity * 0.5,
                    "coverage":          "none",
                    "explanation":       f"LLM validation failed: {exc}",
                    "missing_elements":  [],
                }

            # Step 5 — compute composite confidence
            match_conf = compute_match_confidence(
                embedding_similarity=candidate.embedding_similarity,
                llm_confidence=float(llm_result["confidence"]),
                quality_band=clause_row.quality_band,
            )

            # Persist candidate row
            _write_match_row(
                session, contract_id, clause_id, candidate, llm_result, match_conf
            )

    session.commit()

    # Step 6 — select best match per (contract, sub_requirement)
    select_best_matches(session, contract_id)

    # Step 7 — promote best matches to findings
    promoted = promote_to_findings(session, contract_id)

    # Step 8 — gap detection
    gaps = detect_gaps(session, contract_id, contract_type)
    insert_gap_findings(session, gaps)

    summary = {
        "clauses_processed":    len(clause_rows),
        "candidates_evaluated": total_candidates,
        "llm_calls":            total_llm_calls,
        "llm_failures":         total_llm_failures,
        "findings_promoted":    promoted,
        "gaps_detected":        len(gaps),
    }
    log.info("Stage 5 complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _call_llm_json(
    client: Any,
    system: str,
    user: str,
    required_keys: set[str],
) -> dict:
    """Call the LLM via the Anthropic messages API and parse JSON response.

    Raises ValueError if the response is not valid JSON or is missing required keys.
    Caller is responsible for retry logic.
    """
    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = response.content[0].text.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Non-JSON response: {exc}\nRaw: {raw[:200]}") from exc

    missing = required_keys - set(parsed.keys())
    if missing:
        raise ValueError(f"Response missing required keys: {missing}")

    return parsed


def _batch_embed(client: Any, texts: list[str]) -> list[list[float]]:
    """Call the OpenAI-compatible embedding API and return vectors.

    `client` must expose `embeddings.create(model, input)` (OpenAI SDK compatible).
    """
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def _parse_embedding(embedding_str: Optional[str]) -> Optional[list[float]]:
    """Convert pgvector text representation '[0.1,0.2,...]' to float list."""
    if not embedding_str:
        return None
    try:
        return [float(v) for v in embedding_str.strip("[]").split(",")]
    except (ValueError, AttributeError):
        return None


def _risk_to_severity(clause_risk_score: float) -> str:
    if clause_risk_score >= 80:
        return "critical"
    if clause_risk_score >= 60:
        return "high"
    if clause_risk_score >= 35:
        return "medium"
    return "low"


def _format_partial_recommendation(missing_elements: list[str]) -> str:
    if not missing_elements:
        return "Strengthen the clause to fully address all required elements."
    elements_str = "; ".join(missing_elements)
    return (
        f"Amend the clause to explicitly address the following missing elements: "
        f"{elements_str}."
    )
