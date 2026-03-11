# Contract Analysis Platform — Technical Testing Guide

This document covers everything needed to start, configure, and test the platform before business pilot usage.

---

## Contents

1. [Dependencies & Installation](#1-dependencies--installation)
2. [Configuration](#2-configuration)
3. [Startup Validation](#3-startup-validation)
4. [Starting the Platform](#4-starting-the-platform)
5. [Smoke Test (Quick Verification)](#5-smoke-test-quick-verification)
6. [End-to-End Test Checklist](#6-end-to-end-test-checklist)
7. [Mode Testing (A / B / C)](#7-mode-testing-a--b--c)
8. [Output Verification Reference](#8-output-verification-reference)
9. [Stage 5 Benchmark Evaluation](#9-stage-5-benchmark-evaluation)
10. [Known Behaviors & Non-Issues](#10-known-behaviors--non-issues)

---

## 1. Dependencies & Installation

### Python (backend + pipeline)

Python 3.10 or higher is required.

```bash
# Install all required packages
pip install fastapi uvicorn[standard] sqlalchemy aiofiles python-multipart \
            passlib python-jose[cryptography] bcrypt \
            pdfminer.six python-docx regex

# LLM provider (only required when LLM_ENABLED=true)
pip install anthropic        # for LLM_PROVIDER=anthropic
pip install openai           # for LLM_PROVIDER=openai
```

### Node.js (frontend)

Node.js 18+ is required.

```bash
cd frontend
npm install
```

---

## 2. Configuration

### Environment variables

Copy `.env.example` to `.env` and populate:

```bash
cp .env.example .env
```

Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_ENABLED` | `true` | Master LLM switch. Set `false` for deterministic-only mode. |
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `openai` |
| `LLM_API_KEY` | — | Unified key (or use `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) |
| `LLM_MODEL` | provider default | Override model name |
| `LLM_TIMEOUT_SECONDS` | `60` | Per-request timeout |
| `JWT_SECRET` | random per process | Set a stable secret for persistent sessions |
| `JWT_EXPIRY_HOURS` | `8` | Token lifetime |
| `STAGE5_SEMANTIC_RETRIEVAL_ENABLED` | `true` | TF-IDF candidate retrieval |
| `CONTRACT_EVAL_MODE` | `false` | Benchmark eval mode — **never enable in production** |

### Frontend configuration

The frontend reads from `frontend/.env.local`:

```
NEXT_PUBLIC_API_URL=http://127.0.0.1:8765
```

Adjust the port if you change the backend's bind address.

---

## 3. Startup Validation

Before starting, run the config validator to catch errors early:

```bash
# Deterministic mode (no LLM required)
LLM_ENABLED=false python -m backend.startup_check

# LLM enabled (requires API key in environment)
python -m backend.startup_check
```

The checker verifies:
- Python version ≥ 3.10
- All required packages installed
- LLM provider name is valid (`anthropic` or `openai`)
- API key present when `LLM_ENABLED=true`
- `LLM_TIMEOUT_SECONDS` is a valid positive integer
- `contracts/` and `analyses/` directories are writable

**Expected output when ready:**
```
[PASS] Python version
[PASS] Required packages
[PASS] LLM configuration
[PASS] JWT configuration
[PASS] Filesystem access
All checks passed. Ready to start.
```

---

## 4. Starting the Platform

### Backend

```bash
# From project root (/home/user)
LLM_ENABLED=false uvicorn backend.main:app --host 127.0.0.1 --port 8765 --reload
```

The backend:
- Creates `contracts.db` (SQLite) on first start automatically
- Creates `contracts/` and `analyses/` directories if missing
- Runs database schema migrations idempotently on every startup

No separate migration step is needed.

### Frontend

```bash
cd frontend
npm run dev     # development server on http://localhost:3000
# or
npm run build && npm run start   # production build
```

### Verify backend is up

```bash
curl http://127.0.0.1:8765/health
# Expected: {"status": "ok"}
```

---

## 5. Smoke Test (Quick Verification)

The smoke test exercises the full CLI pipeline end-to-end without the HTTP server. It uses a bundled test contract and produces all pipeline artifacts.

```bash
# Mode A: Deterministic (no LLM required)
python smoke_test.py

# Mode B: With LLM (requires valid API key)
LLM_ENABLED=true ANTHROPIC_API_KEY=sk-ant-... python smoke_test.py
```

**Expected output (deterministic):**
```
31/31 checks passed
Smoke test PASSED — platform is ready for testing.
```

The test verifies:
- Stage 16 ingests the contract and produces clauses
- Stage 4.5 produces obligation analysis
- Stage 5 produces ≥ 5 DIRECT_MATCH records with `_ai_metadata`
- Stage 6 produces the compliance report
- Stage 8 produces remediation proposals with `_ai_metadata`
- Stages 9-14 produce all six audit artifacts
- `CONTRACT_EVAL_MODE=false` means no benchmark artifacts are written

**Artifacts are preserved in `/tmp/cap_smoke_*/` on failure** for inspection.

---

## 6. End-to-End Test Checklist

Use this checklist for manual or scripted verification of the full platform flow via the HTTP API.

### Setup

```bash
BASE=http://127.0.0.1:8765

# Register first user (becomes ADMIN of a new tenant)
curl -s -X POST $BASE/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@test.com","password":"Test1234!","name":"Test Admin","organization_name":"Test Org"}' \
  | jq .

# Obtain JWT token
TOKEN=$(curl -s -X POST $BASE/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@test.com","password":"Test1234!"}' | jq -r .access_token)

AUTH="-H \"Authorization: Bearer $TOKEN\""
```

### Set Org Profile

```bash
curl -s -X PUT $BASE/customers/me/profile \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "regulatory_frameworks": ["ISO27001", "GDPR", "DORA", "NIS2"],
    "industry": "Financial Services"
  }' | jq .
```

### Upload Contract

```bash
curl -s -X POST $BASE/contracts/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@tests/fixtures/smoke_contract.txt" \
  | jq .
# Capture: contract_id, version_id from response

CONTRACT_ID=<id from response>
VERSION_ID=<id from response>
```

### Trigger Analysis

```bash
curl -s -X POST $BASE/contracts/$CONTRACT_ID/versions/$VERSION_ID/analyze \
  -H "Authorization: Bearer $TOKEN" \
  | jq .
```

### Poll for Completion

```bash
curl -s $BASE/contracts/$CONTRACT_ID/status \
  -H "Authorization: Bearer $TOKEN" | jq '{status, current_stage}'
# Repeat until status = "completed" or "failed"
```

### Verify Outputs

```bash
# Risk report
curl -s $BASE/contracts/$CONTRACT_ID/versions/$VERSION_ID/report \
  -H "Authorization: Bearer $TOKEN" | jq '{contract_id, risk_distribution}'

# Negotiation package
curl -s $BASE/contracts/$CONTRACT_ID/versions/$VERSION_ID/negotiation \
  -H "Authorization: Bearer $TOKEN" | jq '{total_items, high_priority}'

# Findings summary
curl -s $BASE/contracts/$CONTRACT_ID/versions/$VERSION_ID/findings/summary \
  -H "Authorization: Bearer $TOKEN" | jq .

# Closure bundle manifest
curl -s $BASE/contracts/$CONTRACT_ID/versions/$VERSION_ID/closure-bundle \
  -H "Authorization: Bearer $TOKEN" | jq .
```

### Checklist Items

- [ ] Contract uploads successfully, version created (v1)
- [ ] Ingestion completes: clauses extracted from smoke contract
- [ ] Stage 4.5 runs: obligation analysis present in analysis outputs
- [ ] Stage 5 runs: `clause_sr_matches.json` present with DIRECT_MATCH records
- [ ] Stage 6 runs: compliance report present (`sr_compliance` section)
- [ ] Stage 8 runs: remediation proposals present
- [ ] Stage 9-14 run: all six artifacts generated (brief, trace, scoring, action plan, negotiation package, risk report)
- [ ] Report endpoint returns JSON with `contract_id` and `risk_distribution`
- [ ] Negotiation endpoint returns `negotiation_items`
- [ ] Findings summary shows SR-level compliance counts
- [ ] Closure bundle manifest lists all artifacts
- [ ] `_ai_metadata` present on Stage 5 match records
- [ ] `_ai_metadata.llm_used` is `false` when `LLM_ENABLED=false`
- [ ] `_ai_metadata.llm_used` is `true` when `LLM_ENABLED=true` and key is valid
- [ ] Upload a second version; verify independent analysis with `version_id` scoping
- [ ] Version compare endpoint returns diff between v1 and v2

---

## 7. Mode Testing (A / B / C)

### Mode A — LLM disabled (deterministic)

All pipeline stages run rule-based fallback only. No API calls are made. No API key required.

```bash
LLM_ENABLED=false python smoke_test.py
# or via backend:
LLM_ENABLED=false uvicorn backend.main:app --port 8765
```

**Expected behavior:**
- Pipeline runs to completion
- `_ai_metadata.llm_used` is always `false`
- `_ai_metadata.provider`, `.model`, `.confidence` are all `null`
- Stage 5 uses deterministic + TF-IDF retrieval; no LLM validation calls
- Stage 4.5: rule-based obligation classification only
- Stage 8: template-based remediation proposals only

### Mode B — LLM enabled with valid credentials

```bash
LLM_ENABLED=true \
ANTHROPIC_API_KEY=sk-ant-... \
python smoke_test.py
```

**Expected behavior:**
- `_ai_metadata.llm_used` is `true` for LLM-augmented records
- `_ai_metadata.provider` is `"anthropic"` (or configured provider)
- Stage 5: LLM validates shortlisted candidates; may upgrade PARTIAL → DIRECT or downgrade
- Stage 4.5: LLM refines obligation classifications
- Stage 8: LLM generates contract-specific remediation language

### Mode C — LLM enabled with missing/invalid credentials

```bash
LLM_ENABLED=true \
ANTHROPIC_API_KEY=invalid-key \
python -m backend.startup_check
# Expected: FAIL on LLM configuration (invalid key detected at startup)

# OR: if key passes format validation but is rejected at runtime:
LLM_ENABLED=true \
ANTHROPIC_API_KEY=sk-ant-invalid \
python smoke_test.py
```

**Expected behavior (safe fallback):**
- Startup check reports the missing/invalid key
- If the key passes startup but fails at runtime: LLM calls retry, then fall back to deterministic
- Pipeline completes successfully with rule-based output
- `_ai_metadata.llm_used` is `false` (fallback activated)
- No pipeline corruption or crash
- Warning logged: `"LLM provider init failed … Falling back to deterministic."`

---

## 8. Output Verification Reference

### Stage 5 match record

```json
{
  "clause_id": "CL-001",
  "framework": "ISO27001",
  "sr_id": "SR-ISO27001-01",
  "match_type": "DIRECT_MATCH",
  "match_confidence": 0.95,
  "extracted_evidence": "...",
  "_ai_metadata": {
    "llm_used": false,
    "provider": null,
    "model": null,
    "prompt_version": null,
    "confidence": null
  },
  "_candidate_metadata": {
    "deterministic_candidate": true,
    "semantic_candidate": false,
    "candidate_source": "deterministic"
  }
}
```

### Stage 6 compliance report top-level keys

```
contract_id, generated_at, sr_compliance, obligation_findings, frameworks_checked
```

### Stage 8 remediation record

```json
{
  "finding_type": "MISSING_SR",
  "sr_id": "SR-GDPR-03",
  "problem_summary": "...",
  "negotiation_guidance": "...",
  "suggested_clause": "...",
  "fallback_option": "...",
  "_ai_metadata": { "llm_used": false, ... }
}
```

### Audit artifacts (stages 9-14)

| File | Key fields |
|------|-----------|
| `contract_negotiation_brief.json` | `contract_id`, `topics`, `overall_risk` |
| `audit_trace_<id>.json` | `contract_id`, `trace_entries` |
| `risk_scoring.json` | `contract_id`, `clause_scores`, `high_priority` |
| `action_plan.json` | `contract_id`, `actions` |
| `negotiation_package.json` | `contract_id`, `negotiation_items`, `total_items` |
| `contract_risk_report.json` | `contract_id`, `risk_distribution`, `top_risk_areas` |

### Evaluation artifacts (only when `CONTRACT_EVAL_MODE=true`)

| File | Purpose |
|------|---------|
| `benchmark_comparison_stage5.json` | Per-clause TP/FP/FN breakdown |
| `benchmark_metrics_stage5.json` | Aggregate P/R/F1 by mode and scoring policy |

These files **must not appear** when `CONTRACT_EVAL_MODE=false` (default).

---

## 9. Stage 5 Benchmark Evaluation

The Stage 5 benchmark tests retrieval and matching quality offline, without an HTTP server.

```bash
# Run benchmark (writes eval artifacts to tests/eval_output/)
CONTRACT_EVAL_MODE=true \
python tests/validate_stage5_eval.py

# Expected: 145/145 checks passed
```

Current benchmark metrics (after catalog refinement):

| Metric | Value |
|--------|-------|
| `det_only` relaxed F1 | 0.9231 |
| `det_only` strict F1 | 0.8462 |
| Shortlist recall (semantic) | 1.0 (14/14) |
| False positives (relaxed) | 0 |

---

## 10. Known Behaviors & Non-Issues

### Stage 6 / audit pipeline exits 1

Exit code 1 from Stage 6 or `contract_audit` means HIGH-severity findings were detected. This is **expected and correct** for a security-relevant contract. The smoke test handles this.

### Stage 5 `PARTIAL_MATCH` on CL-009

CL-009 ("ISMS documentation is regularly reviewed") matches SR-ISO27001-01 on only 1/4 patterns (strict benchmark TP expected DIRECT_MATCH). This is a known gap where ISMS context alone does not produce a DIRECT_MATCH. Behavior is documented in the benchmark.

### TF-IDF synonym limitations

TF-IDF retrieval cannot automatically bridge synonym pairs like "supervisory bodies" ↔ "competent authorities". These gaps are addressed via `retrieval_synonyms` in the SR catalog. If new synonym gaps are identified, add them to the relevant SR entry in `stage5_matching.py`. See `llm/retrieval.py` module docstring for the full list of documented gaps.

### JWT tokens invalidated on restart

If `JWT_SECRET` is not set, a random secret is generated each process start and all active tokens are invalidated. Set a stable `JWT_SECRET` in your `.env` to avoid this during testing.

### SQLite concurrency

The platform uses SQLite in development. It handles moderate concurrent load but is not suitable for high-throughput production. For production, switch to PostgreSQL by updating `DATABASE_URL` in `backend/config.py`.
