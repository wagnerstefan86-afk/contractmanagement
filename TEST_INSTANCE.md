# Test Instance Deployment Guide

> **Scope:** Browser-based testing on a separate machine or VM.
> This is **not** a production setup. No TLS, no secret management, no hardening.

---

## Prerequisites

The target machine needs:

| Tool | Version | Check |
|------|---------|-------|
| Docker | 24+ | `docker --version` |
| Docker Compose plugin | v2 | `docker compose version` |
| Open ports | 3000 (UI), 8765 (API) | check firewall / security group |

---

## 1. Copy the Project

```bash
# From the development machine — rsync the project to the test host
rsync -av --exclude='data/' --exclude='.env' --exclude='__pycache__' \
  /path/to/contract-analysis-platform/ user@testhost:/opt/cap/

# Or clone from git if the project is version-controlled
# git clone <repo-url> /opt/cap && cd /opt/cap
```

---

## 2. Configure Environment Variables

```bash
cd /opt/cap

# Copy the test template
cp .env.test .env
```

Open `.env` in an editor and set **at minimum**:

```bash
# Replace with your test server's IP or hostname
NEXT_PUBLIC_API_URL=http://192.168.1.10:8765

# Generate a stable JWT secret (tokens survive restarts)
# Run once: python3 -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=paste-your-generated-secret-here
```

Everything else in `.env.test` is safe to leave as-is for a first run.

---

## 3. Build and Start

```bash
# Build both images (bakes NEXT_PUBLIC_API_URL into the JS bundle)
docker compose build

# Start in the background
docker compose up -d

# Confirm both containers are running
docker compose ps
```

Expected output:
```
NAME            STATUS          PORTS
cap-backend-1   Up (healthy)    0.0.0.0:8765->8765/tcp
cap-frontend-1  Up              0.0.0.0:3000->3000/tcp
```

The backend healthcheck runs for up to ~60 s on first start (database initialisation + dependency install). The frontend waits for the backend to be healthy before starting.

---

## 4. Verify the Backend is Up

```bash
curl http://<your-host>:8765/health
# Expected: {"status": "ok", "timestamp": "..."}
```

---

## 5. Open the UI

Navigate to:

```
http://<your-host>:3000
```

### First-time bootstrap

The database is empty on a fresh deployment. The registration page accepts a new account without needing a pre-existing customer record **only when the database is empty**.

1. Go to **`/register`**
2. Fill in:
   - **Organisation name** — your test org
   - **Email** and **password**
   - Leave **Customer ID** blank on first registration
3. Submit → you are automatically the `ADMIN` of a new tenant
4. Log in at **`/login`**

> If the database already has data, new users need a `customer_id` issued by an existing ADMIN.

---

## 6. Run a Smoke Test Contract Through the App

### Step A — Set the organisation profile

1. Go to **Settings → Customer Profile** (top-right menu or `/settings/customer-profile`)
2. Fill in at least: **organisation name**, **industry**, **jurisdiction**
3. Save

### Step B — Upload a contract

1. Go to **Dashboard → Upload Contract** (or `/contracts/upload`)
2. Upload any `.pdf`, `.docx`, or `.txt` file
   - A minimal test file is available at `tests/fixtures/smoke_contract.txt`
3. The contract appears in the list with status **Pending**

### Step C — Run analysis

1. Click the contract → **Analyse** button
2. The pipeline runs: ingestion → classification → obligation analysis → SR matching → compliance → remediation → risk scoring → negotiation → audit
3. Watch status update to **Running** then **Completed** (reload or poll)
   - In deterministic mode (LLM_ENABLED=false) this takes a few seconds
   - In LLM mode it can take 1–3 minutes depending on contract length

### Step D — Review results

From the contract detail page:
- **Risk Report** — overall risk distribution and per-clause scores
- **Clause Explorer** — per-clause regulatory matches (SR matches), findings, obligation assessments
- **Negotiation Package** — recommended redline positions
- **Findings** — reviewable finding list with severity and status

---

## 7. Verify Key Fields in API Responses

Run these curl commands to confirm the pipeline metadata is flowing through:

```bash
TOKEN="<paste JWT from browser DevTools → Application → Local Storage → access_token>"
HOST="http://<your-host>:8765"
CONTRACT_ID="<paste from URL bar after uploading>"

# List contracts
curl -s -H "Authorization: Bearer $TOKEN" $HOST/contracts | python3 -m json.tool

# Clause detail (check ai_metadata, candidate_metadata fields)
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HOST/contracts/$CONTRACT_ID/versions/1/clauses" | python3 -m json.tool

# Single clause detail
CLAUSE_ID="<clause_id from above>"
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HOST/contracts/$CONTRACT_ID/versions/1/clauses/$CLAUSE_ID" | python3 -m json.tool
```

In deterministic mode (`LLM_ENABLED=false`) you should see:
```json
"ai_metadata": { "llm_used": false, "provider": null, "model": null }
```

---

## 8. Enable LLM Mode (after deterministic baseline is verified)

Edit `.env`:

```bash
LLM_ENABLED=true
LLM_PROVIDER=anthropic        # or openai
ANTHROPIC_API_KEY=sk-ant-...  # or OPENAI_API_KEY
LLM_TIMEOUT_SECONDS=60
```

Rebuild and restart the **backend only** (frontend does not change):

```bash
docker compose up -d --build backend
```

Run analysis on the same contract again and confirm:
```json
"ai_metadata": { "llm_used": true, "provider": "anthropic", "model": "claude-opus-4-6" }
```

---

## 9. Logs and Troubleshooting

```bash
# Live logs from both services
docker compose logs -f

# Backend only
docker compose logs -f backend

# Frontend only
docker compose logs -f frontend
```

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Frontend shows blank page | `NEXT_PUBLIC_API_URL` wrong | Rebuild with correct IP in `.env` |
| API calls blocked (CORS error in DevTools) | CORS not configured | Backend defaults `CORS_ORIGINS=*`; check backend logs |
| Backend exits on startup with LLM errors | `LLM_ENABLED=true` but no key | Set `LLM_ENABLED=false` or add `ANTHROPIC_API_KEY` |
| Tokens invalid after restart | `JWT_SECRET` not set | Set a stable `JWT_SECRET` in `.env` |
| `502 Bad Gateway` on frontend | Backend not healthy yet | Wait 60 s, then `docker compose ps` |
| Database permission error | `./data` not writable | `chmod -R 777 ./data` (test only) |

---

## 10. Stopping and Cleaning Up

```bash
# Stop containers (data is preserved in ./data/)
docker compose down

# Stop and remove all data volumes (full reset)
docker compose down && rm -rf ./data/

# Remove built images
docker compose down --rmi local
```

---

## Data Layout

All persistent data is written to `./data/` next to `docker-compose.yml`:

```
./data/
  contracts.db          ← SQLite database (users, contracts, analyses, findings)
  contracts/            ← uploaded contract files
  analyses/             ← pipeline JSON artifacts per contract
    <contract_id>/
      stage5_matches.json
      compliance_report.json
      risk_scoring.json
      action_plan.json
      negotiation_package.json
      contract_risk_report.json
      audit_trace_*.json
      closure_bundle/   ← generated when version is approved/rejected
```

Back up `./data/` to preserve test state between sessions.
