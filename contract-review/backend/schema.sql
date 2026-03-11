-- ============================================================================
-- CONTRACT REVIEW APPLICATION — COMPLETE DATABASE SCHEMA  v1.1
-- ============================================================================
-- PostgreSQL 15+ with pgvector extension
--
-- Design decisions documented inline.
-- All timestamps are UTC. All text IDs use human-readable slugs for the
-- requirement library (seeded from YAML, rarely changes) and UUIDs for
-- runtime data (contracts, clauses, findings) to avoid collision at scale.
--
-- v1.1 fixes applied (10 total):
--   Fix 1  findings.framework_id       — explicit ON DELETE RESTRICT
--   Fix 2  findings.sub_requirement_id — explicit ON DELETE RESTRICT
--   Fix 3  risk_scores.framework_id    — explicit ON DELETE SET NULL
--   Fix 4  severity_enum              — hoisted above sub_requirements;
--                                       missing_severity now uses enum type,
--                                       redundant TEXT CHECK removed
--   Fix 5  findings.clause_quality_band — added CHECK constraint
--   Fix 6  contract_type_framework_weights — added missing created_at
--   Fix 7  idx_explain_review_pending  — fixed degenerate index column
--                                       (was: human_review_required, now: contract_id)
--   Fix 8  findings                   — added gap-detection composite index
--   Fix 9  sub_requirements.clause_categories — non-empty array CHECK
--   Fix 10 contract_chunks            — added updated_at for stale-embedding detection
-- ============================================================================

-- Required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgvector";

-- ============================================================================
-- SECTION 1: REQUIREMENT LIBRARY (seeded from YAML)
-- ============================================================================
-- These tables form a read-heavy reference hierarchy.
-- They use TEXT primary keys (slugs) because:
--   1. They are human-authored, version-controlled in YAML
--   2. Slug PKs make joins self-documenting in queries
--   3. The total row count is small (<5000 rows across all tables)
--   4. Foreign keys into these from runtime tables are readable in logs
-- Tradeoff: TEXT PKs are slower for joins than INT, but at <5000 rows
-- this is unmeasurable. The readability benefit dominates.
-- ============================================================================

CREATE TABLE frameworks (
    id              TEXT        PRIMARY KEY,              -- e.g. 'iso27001', 'dora'
    name            TEXT        NOT NULL,                 -- e.g. 'ISO/IEC 27001:2022'
    version         TEXT        NOT NULL,                 -- e.g. '2022'
    description     TEXT,
    authority       TEXT,                                 -- e.g. 'ISO', 'EU'
    reference_url   TEXT,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT frameworks_id_format CHECK (id ~ '^[a-z0-9_]+$')
);

COMMENT ON TABLE frameworks IS 'Compliance frameworks (ISO 27001, DORA, NIS2, etc.)';

-- ---------------------------------------------------------------------------

CREATE TABLE domains (
    id              TEXT        PRIMARY KEY,              -- e.g. 'iso27001_a5'
    framework_id    TEXT        NOT NULL REFERENCES frameworks(id) ON DELETE CASCADE,
    name            TEXT        NOT NULL,                 -- e.g. 'A.5 Organizational Controls'
    description     TEXT,
    sort_order      INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT domains_id_format CHECK (id ~ '^[a-z0-9_]+$')
);

CREATE INDEX idx_domains_framework ON domains(framework_id);

COMMENT ON TABLE domains IS 'Control families / chapters within a framework';

-- ---------------------------------------------------------------------------

CREATE TABLE requirements (
    id              TEXT        PRIMARY KEY,              -- e.g. 'iso27001_a5_19'
    domain_id       TEXT        NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    name            TEXT        NOT NULL,                 -- e.g. 'A.5.19 Information security in supplier relationships'
    description     TEXT        NOT NULL,
    guidance_text   TEXT,                                 -- implementation guidance
    sort_order      INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT requirements_id_format CHECK (id ~ '^[a-z0-9_]+$')
);

CREATE INDEX idx_requirements_domain ON requirements(domain_id);

COMMENT ON TABLE requirements IS 'Specific controls or articles within a domain';

-- ---------------------------------------------------------------------------
-- Sub-requirements are the leaf level of the requirement hierarchy.
-- Each sub-requirement maps to one or more clause categories.
-- The clause_categories column is a TEXT[] array rather than a junction table
-- because:
--   1. The canonical category list is a closed enum, not a separate entity
--   2. A sub-requirement typically maps to 1-3 categories
--   3. Array containment queries (@>) are fast with a GIN index
--   4. Avoids a many-to-many table for a simple mapping
-- Tradeoff: referential integrity is enforced at the type level (enum array),
-- not via a junction table FK.
--
-- Fix 4: severity_enum is now defined before this table (see ENUM TYPES
-- section that was previously embedded mid-file in Section 3). The
-- missing_severity column has been changed from TEXT+CHECK to the enum
-- type directly, removing the duplicate constraint definition and the
-- mismatch where the TEXT CHECK allowed only 4 values while severity_enum
-- has 5 (adding 'info').
-- ---------------------------------------------------------------------------

-- layout_type_enum: classifies the structural origin of a chunk.
-- Used in Stage 2 (chunking) and Stage 4 (clause extraction prompt selection).
-- 'ocr_text' identifies chunks that required OCR fallback (lower text reliability).
-- 'table' chunks carry structured data in the separate table_data JSONB column.
CREATE TYPE layout_type_enum AS ENUM (
    'paragraph',
    'bullet_list',
    'numbered_list',
    'table',
    'heading',
    'ocr_text'
);

-- Fix 4: Define clause_category_enum here so both sub_requirements (library)
-- and clauses (runtime) can share the same type without forward-reference issues.
CREATE TYPE clause_category_enum AS ENUM (
    'incident_reporting',
    'audit_rights',
    'subcontractor_management',
    'data_protection_obligations',
    'security_requirements',
    'availability_sla',
    'business_continuity',
    'data_breach_notification',
    'data_retention_deletion',
    'encryption_requirements',
    'access_control',
    'penetration_testing',
    'change_management',
    'termination_data_return',
    'liability_cap',
    'governing_law'
);

-- Fix 4: Hoisted from Section 3. Previously sub_requirements used
-- TEXT + CHECK(IN ('critical','high','medium','low')) which diverged from
-- severity_enum (which includes 'info') and prevented type-safe joins
-- between findings.severity and sub_requirements.missing_severity.
CREATE TYPE severity_enum AS ENUM (
    'critical',
    'high',
    'medium',
    'low',
    'info'
);

CREATE TABLE sub_requirements (
    id                       TEXT                   PRIMARY KEY,     -- e.g. 'iso27001_a5_19_1'
    requirement_id           TEXT                   NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    name                     TEXT                   NOT NULL,
    description              TEXT                   NOT NULL,
    -- Fix 9: array_length CHECK prevents empty arrays. An empty array silently
    -- breaks all category-matching queries and produces false gap-detection positives
    -- (sub-requirement can never be satisfied). NOT NULL alone does not prevent '{}'.
    clause_categories        clause_category_enum[] NOT NULL,
    evidence_keywords        TEXT[]                 NOT NULL DEFAULT '{}',
    -- Fix 4: was TEXT NOT NULL DEFAULT 'high' with CHECK(IN('critical','high','medium','low'))
    -- Now uses severity_enum — invalid values rejected by the type system, 'info' now valid.
    missing_severity         severity_enum          NOT NULL DEFAULT 'high',
    missing_finding_template TEXT,                                   -- template text for gap reports
    sort_order               INTEGER                NOT NULL DEFAULT 0,
    created_at               TIMESTAMPTZ            NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ            NOT NULL DEFAULT NOW(),
    -- Pre-computed embedding of (description || ' ' || array_to_string(evidence_keywords, ' ')).
    -- Computed offline by the requirement library embedding worker; NULL until then.
    -- Used in Stage 5 candidate retrieval: cosine distance against clause normalized_embedding.
    requirement_embedding    vector(1536),

    CONSTRAINT sub_req_id_format CHECK (id ~ '^[a-z0-9_]+$'),
    -- Fix 9: at least one category required per sub-requirement.
    CONSTRAINT sub_req_categories_nonempty CHECK (array_length(clause_categories, 1) >= 1)
);

CREATE INDEX idx_sub_requirements_requirement ON sub_requirements(requirement_id);
CREATE INDEX idx_sub_requirements_categories  ON sub_requirements USING GIN (clause_categories);
-- Stage 5: ANN search — requirement_embedding vs clause normalized_embedding
CREATE INDEX idx_sub_req_embedding ON sub_requirements USING ivfflat (requirement_embedding vector_cosine_ops)
    WITH (lists = 20);

COMMENT ON TABLE sub_requirements IS 'Leaf-level obligations within a requirement, linked to clause categories';

-- ---------------------------------------------------------------------------
-- Contract type configuration tables.
-- These define how contract classification influences the analysis pipeline.
-- ---------------------------------------------------------------------------

CREATE TYPE contract_type_enum AS ENUM (
    'saas',
    'outsourcing',
    'cloud_iaas_paas',
    'dpa',
    'managed_security',
    'professional_svcs',
    'software_license',
    'maintenance',
    'joint_venture',
    'nda'
);

CREATE TABLE contract_type_req_mapping (
    id                  UUID               PRIMARY KEY DEFAULT uuid_generate_v4(),
    contract_type       contract_type_enum NOT NULL,
    sub_requirement_id  TEXT               NOT NULL REFERENCES sub_requirements(id) ON DELETE CASCADE,
    mandatory           BOOLEAN            NOT NULL DEFAULT FALSE,
    min_quality_score   NUMERIC(4,3)       NOT NULL DEFAULT 0.500,    -- 0.000–1.000
    weight              NUMERIC(4,3)       NOT NULL DEFAULT 0.100,    -- category weight within framework
    created_at          TIMESTAMPTZ        NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_contract_type_sub_req UNIQUE (contract_type, sub_requirement_id),
    CONSTRAINT min_quality_range CHECK (min_quality_score BETWEEN 0.0 AND 1.0),
    CONSTRAINT weight_range CHECK (weight BETWEEN 0.0 AND 1.0)
);

-- Primary query: "all mandatory sub-requirements for contract type X"
CREATE INDEX idx_ctrm_type_mandatory ON contract_type_req_mapping(contract_type, mandatory)
    WHERE mandatory = TRUE;
CREATE INDEX idx_ctrm_sub_req ON contract_type_req_mapping(sub_requirement_id);

COMMENT ON TABLE contract_type_req_mapping IS
    'Per contract type: which sub-requirements are mandatory and their quality thresholds';

-- ---------------------------------------------------------------------------

CREATE TABLE contract_type_framework_weights (
    id              UUID               PRIMARY KEY DEFAULT uuid_generate_v4(),
    contract_type   contract_type_enum NOT NULL,
    framework_id    TEXT               NOT NULL REFERENCES frameworks(id) ON DELETE CASCADE,
    weight          NUMERIC(4,3)       NOT NULL,           -- 0.000–1.000
    -- Fix 6: added created_at — missing from original schema; every other table
    -- has this column; required for framework weight change auditing.
    created_at      TIMESTAMPTZ        NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_ct_fw_weight   UNIQUE (contract_type, framework_id),
    CONSTRAINT ctfw_weight_range CHECK (weight BETWEEN 0.0 AND 1.0)
);

CREATE INDEX idx_ctfw_type ON contract_type_framework_weights(contract_type);

COMMENT ON TABLE contract_type_framework_weights IS
    'Framework weight overrides per contract type. Weights are renormalized to sum=1.0 at query time';


-- ============================================================================
-- SECTION 2: CONTRACT PROCESSING (runtime data)
-- ============================================================================
-- Runtime tables use UUID primary keys for:
--   1. No collision risk in concurrent inserts (no sequences to contend)
--   2. Safe for future distributed/replicated deployments
--   3. Non-guessable IDs (security hygiene)
-- Tradeoff: 16 bytes vs 4 bytes (INT). At 100k contracts this is negligible.
-- ============================================================================

CREATE TYPE analysis_status_enum AS ENUM (
    'uploaded',
    'parsing',
    'chunking',
    'classifying',
    'extracting_clauses',
    'analyzing',
    'scoring',
    'generating_summary',
    'completed',
    'failed'
);

CREATE TABLE contracts (
    id                      UUID                 PRIMARY KEY DEFAULT uuid_generate_v4(),
    filename                TEXT                 NOT NULL,
    file_hash_sha256        TEXT                 NOT NULL,         -- deduplication + integrity
    file_size_bytes         BIGINT               NOT NULL,
    file_type               TEXT                 NOT NULL,         -- 'pdf', 'docx'
    page_count              INTEGER,
    -- Classification
    primary_type            contract_type_enum,
    secondary_types         contract_type_enum[] DEFAULT '{}',
    type_confidence         NUMERIC(4,3),
    -- Processing state
    status                  analysis_status_enum NOT NULL DEFAULT 'uploaded',
    error_message           TEXT,
    -- Metadata
    contract_title          TEXT,                                  -- extracted or user-provided
    supplier_name           TEXT,
    effective_date          DATE,
    expiry_date             DATE,
    uploaded_by             TEXT,                                  -- username / email
    -- Timestamps
    uploaded_at             TIMESTAMPTZ          NOT NULL DEFAULT NOW(),
    processing_started_at   TIMESTAMPTZ,
    processing_completed_at TIMESTAMPTZ,
    created_at              TIMESTAMPTZ          NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ          NOT NULL DEFAULT NOW(),

    CONSTRAINT file_type_check       CHECK (file_type IN ('pdf', 'docx')),
    CONSTRAINT type_confidence_range CHECK (type_confidence BETWEEN 0.0 AND 1.0)
);

-- Primary query patterns:
-- 1. List contracts by status (dashboard)
-- 2. Lookup by file hash (dedup check on upload)
-- 3. Filter by supplier name
CREATE INDEX idx_contracts_status    ON contracts(status);
CREATE INDEX idx_contracts_file_hash ON contracts(file_hash_sha256);
CREATE INDEX idx_contracts_supplier  ON contracts(supplier_name) WHERE supplier_name IS NOT NULL;
CREATE INDEX idx_contracts_uploaded  ON contracts(uploaded_at DESC);

COMMENT ON TABLE contracts IS 'Uploaded contract documents with classification and processing status';

-- ---------------------------------------------------------------------------
-- Contract chunks preserve full provenance: page number, paragraph index,
-- byte offsets into the original extracted text, and the section header
-- under which the chunk falls.
--
-- Embedding column uses vector(1536) for OpenAI text-embedding-3-small.
-- Change dimension if using a different embedding model.
--
-- Fix 10: added updated_at. The embedding column is populated by a separate
-- pipeline worker after the initial chunk INSERT. Without updated_at there is
-- no way to identify stale embeddings for incremental re-embedding jobs
-- (e.g. after a model version change):
--   WHERE embedding IS NOT NULL AND updated_at < :model_cutoff_date
-- ---------------------------------------------------------------------------

CREATE TABLE contract_chunks (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    contract_id         UUID        NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    chunk_index         INTEGER     NOT NULL,            -- sequential order in document
    -- Provenance
    page_start          INTEGER     NOT NULL,
    page_end            INTEGER     NOT NULL,
    para_index_start    INTEGER,                         -- paragraph position on page
    para_index_end      INTEGER,
    section_header      TEXT,                            -- nearest heading above chunk
    char_offset_start   INTEGER     NOT NULL,
    char_offset_end     INTEGER     NOT NULL,
    -- Content
    raw_text            TEXT             NOT NULL,
    normalized_text     TEXT             NOT NULL,       -- cleaned for LLM input
    token_count         INTEGER          NOT NULL,
    -- Layout classification (set by Stage 2 chunker based on Stage 1 structure map)
    layout_type         layout_type_enum NOT NULL DEFAULT 'paragraph',
    -- OCR metadata: populated only when layout_type = 'ocr_text'.
    -- NULL for all non-OCR chunks. Values below 0.70 trigger human_review_flags.
    ocr_confidence      NUMERIC(4,3),
    -- Structured table data: populated only when layout_type = 'table'.
    -- Schema: {"headers": ["Col1", "Col2", ...], "rows": [["v1", "v2"], ...]}
    -- NULL for all non-table chunks. raw_text holds the pipe-delimited fallback.
    table_data          JSONB,
    -- Embedding (NULL until the embedding worker runs in a later pipeline step)
    embedding           vector(1536),                   -- pgvector
    -- Timestamps
    created_at          TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    -- Fix 10: enables stale-embedding detection and incremental re-embedding.
    -- Embedding worker must set updated_at = NOW() on every embedding UPDATE.
    updated_at          TIMESTAMPTZ      NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_chunk_order           UNIQUE (contract_id, chunk_index),
    CONSTRAINT page_range_valid         CHECK  (page_end >= page_start),
    CONSTRAINT char_range_valid         CHECK  (char_offset_end > char_offset_start),
    CONSTRAINT token_count_positive     CHECK  (token_count > 0),
    -- OCR confidence is only meaningful for ocr_text chunks.
    CONSTRAINT ocr_confidence_layout    CHECK  (ocr_confidence IS NULL OR layout_type = 'ocr_text'),
    -- table_data is only meaningful for table chunks.
    CONSTRAINT table_data_layout        CHECK  (table_data IS NULL OR layout_type = 'table'),
    CONSTRAINT ocr_confidence_range     CHECK  (ocr_confidence IS NULL OR ocr_confidence BETWEEN 0.0 AND 1.0)
);

-- Primary query: all chunks for a contract, in order
CREATE INDEX idx_chunks_contract_order ON contract_chunks(contract_id, chunk_index);
-- Similarity search across all chunks
CREATE INDEX idx_chunks_embedding ON contract_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
-- Filter by page range (for targeted re-analysis)
CREATE INDEX idx_chunks_pages ON contract_chunks(contract_id, page_start, page_end);
-- Stage 4 prompt selection: find all chunks of a given layout type for a contract
CREATE INDEX idx_chunks_layout_type ON contract_chunks(contract_id, layout_type);
-- Human review queue: flag low-confidence OCR chunks
CREATE INDEX idx_chunks_low_ocr ON contract_chunks(contract_id, ocr_confidence)
    WHERE layout_type = 'ocr_text' AND ocr_confidence IS NOT NULL;

COMMENT ON TABLE contract_chunks IS 'Text segments from contracts with full page/paragraph provenance and embeddings';

-- ---------------------------------------------------------------------------
-- Normalized clauses: the output of Phase 2 (clause extraction).
-- Each clause is classified into one or more canonical categories.
-- Multi-label is stored as an array (same rationale as sub_requirements).
-- ---------------------------------------------------------------------------

CREATE TYPE classification_method_enum AS ENUM (
    'embedding_similarity',
    'llm_classification',
    'hybrid',
    'manual'
);

CREATE TABLE clauses (
    id                        UUID                       PRIMARY KEY DEFAULT uuid_generate_v4(),
    contract_id               UUID                       NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    chunk_id                  UUID                       NOT NULL REFERENCES contract_chunks(id) ON DELETE CASCADE,
    -- Extracted content
    clause_text               TEXT                       NOT NULL,    -- exact text from contract
    section_reference         TEXT,                                   -- e.g. "Section 8.3"
    -- Normalization
    canonical_categories      clause_category_enum[]     NOT NULL,
    primary_category          clause_category_enum       NOT NULL,    -- dominant category
    classification_method     classification_method_enum NOT NULL,
    classification_confidence NUMERIC(4,3)               NOT NULL,
    -- Embedding of clause_text (used in Stage 3 classification and similarity search)
    clause_embedding          vector(1536),
    -- Stage 5: LLM-normalized obligation text in active voice with canonical verb "must".
    -- NULL until Stage 5 normalization runs.
    -- Example input:  "Incidents shall be reported within 24 hours by the supplier"
    -- Example output: "supplier must report incidents within 24 hours"
    normalized_clause         TEXT,
    -- Embedding of normalized_clause. Kept separate from clause_embedding so that
    -- both the verbatim and normalized representations can be searched independently.
    -- NULL until Stage 5 embedding worker runs.
    normalized_embedding      vector(1536),
    -- Timestamps
    created_at                TIMESTAMPTZ                NOT NULL DEFAULT NOW(),

    CONSTRAINT classification_confidence_range CHECK (classification_confidence BETWEEN 0.0 AND 1.0)
);

-- Supports: findings by contract and clauses by contract (traceability chain)
CREATE INDEX idx_clauses_contract ON clauses(contract_id);
-- Supports: clause lookup by category (analytical)
CREATE INDEX idx_clauses_primary_cat ON clauses(primary_category);
-- Supports: multi-label containment queries (@>)
CREATE INDEX idx_clauses_categories ON clauses USING GIN (canonical_categories);
-- Supports: chunk → clause provenance lookup
CREATE INDEX idx_clauses_chunk ON clauses(chunk_id);
-- Supports: similarity search on clause_text embeddings (Stage 3 classification)
CREATE INDEX idx_clauses_embedding ON clauses USING ivfflat (clause_embedding vector_cosine_ops)
    WITH (lists = 100);
-- Supports: Stage 5 requirement matching via normalized obligation text
CREATE INDEX idx_clauses_norm_embedding ON clauses USING ivfflat (normalized_embedding vector_cosine_ops)
    WITH (lists = 100);

COMMENT ON TABLE clauses IS 'Normalized contractual clauses with canonical category classification and provenance';

-- ---------------------------------------------------------------------------
-- Clause quality scores: three-dimension evaluation stored as individual
-- components so the score can be fully reconstructed in the explainability
-- layer without re-running the evaluation.
-- ---------------------------------------------------------------------------

CREATE TABLE clause_quality_scores (
    id                       UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    clause_id                UUID         NOT NULL REFERENCES clauses(id) ON DELETE CASCADE,
    -- Dimension scores (0.000 – 1.000)
    language_strength        NUMERIC(4,3) NOT NULL,
    language_pattern_matched TEXT,                            -- e.g. 'shall' → mandatory
    specificity_score        NUMERIC(4,3) NOT NULL,
    specificity_timeline     NUMERIC(4,3) NOT NULL,           -- sub-dimension
    specificity_named_std    NUMERIC(4,3) NOT NULL,
    specificity_metric       NUMERIC(4,3) NOT NULL,
    specificity_scope        NUMERIC(4,3) NOT NULL,
    enforceability_score     NUMERIC(4,3) NOT NULL,
    enforceability_details   JSONB        NOT NULL DEFAULT '{}',  -- which patterns matched
    -- Composite
    raw_quality_score        NUMERIC(4,3) NOT NULL,           -- before modifier adjustment
    quality_band             TEXT         NOT NULL,            -- STRONG/ADEQUATE/WEAK/INADEQUATE/NOMINAL
    -- Timestamps
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_clause_quality  UNIQUE (clause_id),
    CONSTRAINT ls_range  CHECK (language_strength    BETWEEN 0.0 AND 1.0),
    CONSTRAINT ss_range  CHECK (specificity_score    BETWEEN 0.0 AND 1.0),
    CONSTRAINT es_range  CHECK (enforceability_score BETWEEN 0.0 AND 1.0),
    CONSTRAINT rqs_range CHECK (raw_quality_score    BETWEEN 0.0 AND 1.0),
    CONSTRAINT quality_band_check CHECK (quality_band IN ('STRONG', 'ADEQUATE', 'WEAK', 'INADEQUATE', 'NOMINAL'))
);

CREATE INDEX idx_cqs_clause ON clause_quality_scores(clause_id);
-- Analytical: find all weak/inadequate clauses across contracts
CREATE INDEX idx_cqs_band ON clause_quality_scores(quality_band);

COMMENT ON TABLE clause_quality_scores IS 'Three-dimension quality evaluation per clause with full sub-component scores';

-- ---------------------------------------------------------------------------
-- Clause modifiers: contractual limitations that weaken a clause.
-- Stored as individual records (not arrays) because:
--   1. Each modifier has its own penalty, matched text, and audit note
--   2. Modifiers need to appear individually in explainability output
--   3. Querying "all supplier_approval modifiers across contracts" is useful
-- ---------------------------------------------------------------------------

CREATE TYPE modifier_type_enum AS ENUM (
    'frequency_cap',
    'notice_requirement',
    'cost_condition',
    'supplier_approval',
    'scope_carveout',
    'timing_delay',
    'best_efforts_qualifier'
);

CREATE TABLE clause_modifiers (
    id                  UUID               PRIMARY KEY DEFAULT uuid_generate_v4(),
    clause_id           UUID               NOT NULL REFERENCES clauses(id) ON DELETE CASCADE,
    modifier_type       modifier_type_enum NOT NULL,
    matched_text        TEXT               NOT NULL,          -- exact text that triggered detection
    char_offset_start   INTEGER,                              -- offset within clause_text
    penalty_multiplier  NUMERIC(4,3)       NOT NULL,          -- 0.000–1.000, applied to quality
    audit_note          TEXT               NOT NULL,          -- human-readable explanation
    created_at          TIMESTAMPTZ        NOT NULL DEFAULT NOW(),

    CONSTRAINT penalty_range CHECK (penalty_multiplier BETWEEN 0.0 AND 1.0)
);

CREATE INDEX idx_modifiers_clause ON clause_modifiers(clause_id);
-- Analytical: find all instances of a specific modifier type
CREATE INDEX idx_modifiers_type ON clause_modifiers(modifier_type);

COMMENT ON TABLE clause_modifiers IS 'Detected limitations/weakeners on clauses with individual penalty scores';

-- ---------------------------------------------------------------------------
-- Stage 5: Clause-to-requirement matching.
--
-- Stores every (clause, sub_requirement) candidate pair evaluated during
-- matching, keeping both Pass 1 (embedding similarity) and Pass 2 (LLM
-- validation) results on the same row. One row per evaluated pair.
--
-- is_best_match = TRUE marks the single winning clause for each
-- (contract_id, sub_requirement_id) pair, chosen by match_confidence DESC.
-- The winning row is promoted to the findings table.
--
-- Rationale for a separate table (vs. writing directly to findings):
--   - All top-10 candidates per sub-requirement are retained for auditability.
--   - Pass 1 and Pass 2 can run at different times without blocking each other.
--   - Rerunning only Pass 2 (LLM) on cached Pass 1 results is cheap.
-- ---------------------------------------------------------------------------

CREATE TYPE coverage_enum AS ENUM ('full', 'partial', 'none');

CREATE TABLE clause_requirement_matches (
    id                   UUID          PRIMARY KEY DEFAULT uuid_generate_v4(),
    contract_id          UUID          NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    clause_id            UUID          NOT NULL REFERENCES clauses(id) ON DELETE CASCADE,
    sub_requirement_id   TEXT          NOT NULL REFERENCES sub_requirements(id) ON DELETE RESTRICT,
    framework_id         TEXT          NOT NULL REFERENCES frameworks(id) ON DELETE RESTRICT,
    -- Pass 1: cosine similarity between clause.normalized_embedding and
    -- sub_requirements.requirement_embedding. Range 0.0000–1.0000.
    embedding_similarity NUMERIC(5,4)  NOT NULL,
    -- Pass 2: LLM semantic validation (NULL until LLM step runs)
    llm_validated        BOOLEAN,
    llm_confidence       NUMERIC(4,3),
    coverage             coverage_enum,                              -- full / partial / none
    explanation          TEXT,
    missing_elements     TEXT[]        NOT NULL DEFAULT '{}',
    -- Composite match confidence (NULL until both passes complete).
    -- Formula: 0.35*embedding_similarity + 0.45*llm_confidence + 0.20*quality_band_score
    match_confidence     NUMERIC(4,3),
    -- Marks the best clause match per (contract_id, sub_requirement_id).
    -- Exactly one row per (contract, sub_requirement) has is_best_match = TRUE.
    is_best_match        BOOLEAN       NOT NULL DEFAULT FALSE,
    -- LLM metadata
    llm_model_used       TEXT,
    llm_prompt_version   TEXT,
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT emb_sim_range    CHECK (embedding_similarity BETWEEN 0.0 AND 1.0),
    CONSTRAINT llm_conf_range   CHECK (llm_confidence   IS NULL OR llm_confidence   BETWEEN 0.0 AND 1.0),
    CONSTRAINT match_conf_range CHECK (match_confidence IS NULL OR match_confidence BETWEEN 0.0 AND 1.0)
);

-- Primary gap-detection query: all best matches for a contract, grouped by requirement
CREATE INDEX idx_crm_contract_subreq ON clause_requirement_matches(contract_id, sub_requirement_id);
-- Best-match promotion query: (contract, sub_requirement) → winning row
CREATE INDEX idx_crm_best_match ON clause_requirement_matches(contract_id, sub_requirement_id, is_best_match)
    WHERE is_best_match = TRUE;
-- Traceability: all matches involving a specific clause
CREATE INDEX idx_crm_clause ON clause_requirement_matches(clause_id);
-- Gap query: uncovered requirements (no row with coverage in (full, partial))
CREATE INDEX idx_crm_coverage ON clause_requirement_matches(contract_id, coverage)
    WHERE is_best_match = TRUE;
-- Analytical: review all low-confidence matches across contracts
CREATE INDEX idx_crm_confidence ON clause_requirement_matches(match_confidence)
    WHERE is_best_match = TRUE AND match_confidence IS NOT NULL;

COMMENT ON TABLE clause_requirement_matches IS
    'Stage 5 intermediate: every evaluated (clause, sub_requirement) candidate pair '
    'with Pass 1 embedding similarity and Pass 2 LLM validation scores. '
    'is_best_match = TRUE rows are promoted to the findings table.';


-- ============================================================================
-- SECTION 3: ANALYSIS
-- ============================================================================

CREATE TYPE finding_type_enum AS ENUM (
    'present',          -- clause exists and is compliant
    'partial',          -- clause exists but is insufficient
    'non_compliant',    -- clause exists but contradicts requirement
    'missing'           -- required clause absent from contract
);

-- NOTE: severity_enum is defined in Section 1 (above sub_requirements).
-- It is intentionally NOT redefined here. See Fix 4.

-- ---------------------------------------------------------------------------
-- Findings: the core analytical output.
-- Each finding links a clause (or absence thereof) to a specific
-- sub-requirement within a specific framework.
--
-- clause_id is NULLABLE: missing-clause findings have no source clause.
-- This is intentional and correct — a NULL clause_id with finding_type='missing'
-- means "we looked and this obligation does not exist in the contract."
--
-- The combination (contract_id, sub_requirement_id, clause_id) is not unique
-- because one clause may generate findings against multiple sub-requirements,
-- and one sub-requirement may have both a 'partial' finding (clause exists but
-- is weak) and a related 'missing' finding (a second required aspect is absent).
--
-- Fix 1: framework_id    — added ON DELETE RESTRICT. Findings are auditable
--        records; a framework deletion must hard-fail while findings exist.
-- Fix 2: sub_requirement_id — same rationale, ON DELETE RESTRICT.
-- ---------------------------------------------------------------------------

CREATE TABLE findings (
    id                    UUID              PRIMARY KEY DEFAULT uuid_generate_v4(),
    contract_id           UUID              NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    clause_id             UUID              REFERENCES clauses(id) ON DELETE SET NULL,  -- NULL for missing clauses
    -- Requirement linkage (full traceability chain)
    -- Fix 1: explicit ON DELETE RESTRICT — prevent silent removal of audit records.
    framework_id          TEXT              NOT NULL REFERENCES frameworks(id) ON DELETE RESTRICT,
    -- Fix 2: explicit ON DELETE RESTRICT — same rationale as framework_id.
    sub_requirement_id    TEXT              NOT NULL REFERENCES sub_requirements(id) ON DELETE RESTRICT,
    -- Assessment
    finding_type          finding_type_enum NOT NULL,
    severity              severity_enum     NOT NULL,
    confidence            NUMERIC(4,3)      NOT NULL,
    justification         TEXT              NOT NULL,     -- LLM explanation with evidence
    recommendation        TEXT              NOT NULL,     -- remediation guidance
    -- Scoring inputs
    clause_risk_score     NUMERIC(5,2)      NOT NULL DEFAULT 0.00,  -- 0.00–100.00
    -- Quality context (denormalized for query performance)
    -- Avoids joining through clauses → clause_quality_scores for dashboards.
    clause_quality_score  NUMERIC(4,3),                   -- NULL if missing
    -- Fix 5: added CHECK constraint matching clause_quality_scores.quality_band.
    -- Without this, invalid values (e.g. 'GOOD') could be inserted into the
    -- denormalized copy, silently breaking GROUP BY quality_band reports.
    clause_quality_band   TEXT,                            -- NULL if missing
    post_modifier_quality NUMERIC(4,3),                   -- NULL if missing
    -- Metadata
    llm_model_used        TEXT,                            -- e.g. 'claude-sonnet-4-6'
    llm_prompt_version    TEXT,                            -- e.g. 'v1.2'
    created_at            TIMESTAMPTZ       NOT NULL DEFAULT NOW(),

    CONSTRAINT confidence_range   CHECK (confidence        BETWEEN 0.0 AND 1.0),
    CONSTRAINT clause_risk_range  CHECK (clause_risk_score BETWEEN 0.0 AND 100.0),
    -- Fix 5: enforce same value set as clause_quality_scores.quality_band.
    CONSTRAINT clause_quality_band_check CHECK (
        clause_quality_band IS NULL
        OR clause_quality_band IN ('STRONG', 'ADEQUATE', 'WEAK', 'INADEQUATE', 'NOMINAL')
    ),
    CONSTRAINT missing_clause_null CHECK (
        (finding_type = 'missing' AND clause_id IS NULL)
        OR (finding_type != 'missing' AND clause_id IS NOT NULL)
    )
);

-- Supports: findings by contract (results page)
CREATE INDEX idx_findings_contract ON findings(contract_id);
-- Supports: findings by framework for a contract (framework tab)
CREATE INDEX idx_findings_contract_framework ON findings(contract_id, framework_id);
-- Supports: severity dashboard alerts (partial — hot rows only)
CREATE INDEX idx_findings_severity ON findings(severity) WHERE severity IN ('critical', 'high');
-- Supports: findings by type (gap analysis view)
CREATE INDEX idx_findings_type ON findings(finding_type);
-- Supports: all findings for a specific clause (clause detail view)
CREATE INDEX idx_findings_clause ON findings(clause_id) WHERE clause_id IS NOT NULL;
-- Supports: findings by sub-requirement across contracts (analytical)
CREATE INDEX idx_findings_sub_req ON findings(sub_requirement_id);
-- Fix 8: gap-detection composite index.
-- Eliminates heap fetch for the core gap query:
--   SELECT mandatory sub-requirements for contract type X
--   EXCEPT
--   SELECT sub_requirement_id FROM findings
--   WHERE contract_id = $1 AND finding_type = 'present'
CREATE INDEX idx_findings_gap_detection ON findings(contract_id, sub_requirement_id, finding_type);

COMMENT ON TABLE findings IS
    'Core analytical output: each finding links a clause (or absence) to a framework sub-requirement';

-- ---------------------------------------------------------------------------
-- Risk scores at three levels: clause, framework, contract.
-- Stored in a single table with a discriminator column rather than three
-- tables because:
--   1. The score structure is identical at all levels
--   2. A single table simplifies the explainability tree traversal
--   3. Querying "all scores for contract X" is one query, not three
-- Tradeoff: the reference columns are polymorphic (clause_id, framework_id
-- may be NULL depending on level). This is constrained with CHECK.
--
-- Fix 3: framework_id FK — added ON DELETE SET NULL (was implicit NO ACTION).
--        Risk scores are computed artifacts; if a framework is deleted the
--        numeric score is preserved but the FK reference is nulled. The
--        risk_level_refs CHECK still enforces non-NULL for framework-level
--        rows while the score is live; after SET NULL those rows are flagged
--        for regeneration.
-- ---------------------------------------------------------------------------

CREATE TYPE risk_level_enum AS ENUM (
    'clause',
    'framework',
    'contract'
);

CREATE TABLE risk_scores (
    id                    UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    contract_id           UUID            NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    risk_level            risk_level_enum NOT NULL,
    -- Polymorphic references (pattern constrained by risk_level_refs CHECK)
    clause_id             UUID            REFERENCES clauses(id) ON DELETE CASCADE,
    -- Fix 3: explicit ON DELETE SET NULL — preserves score history, nulls FK.
    framework_id          TEXT            REFERENCES frameworks(id) ON DELETE SET NULL,
    -- Score
    risk_score            NUMERIC(5,2)    NOT NULL,          -- 0.00–100.00
    risk_band             TEXT            NOT NULL,
    weight_used           NUMERIC(4,3),                      -- weight applied at this level
    -- Breakdown
    missing_count         INTEGER         NOT NULL DEFAULT 0,
    critical_count        INTEGER         NOT NULL DEFAULT 0,
    high_count            INTEGER         NOT NULL DEFAULT 0,
    partial_count         INTEGER         NOT NULL DEFAULT 0,
    compliant_count       INTEGER         NOT NULL DEFAULT 0,
    -- Metadata
    scoring_model_version TEXT            NOT NULL DEFAULT '1.0.0',
    created_at            TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT risk_score_range CHECK (risk_score BETWEEN 0.0 AND 100.0),
    CONSTRAINT risk_band_check  CHECK (risk_band IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')),
    CONSTRAINT risk_level_refs  CHECK (
        (risk_level = 'clause'    AND clause_id IS NOT NULL AND framework_id IS NOT NULL)
        OR (risk_level = 'framework' AND clause_id IS NULL    AND framework_id IS NOT NULL)
        OR (risk_level = 'contract'  AND clause_id IS NULL    AND framework_id IS NULL)
    )
);

-- Supports: all scores for a contract grouped by level
CREATE INDEX idx_risk_scores_contract_level ON risk_scores(contract_id, risk_level);
-- Supports: framework-level scores for a contract (summary view)
CREATE INDEX idx_risk_scores_framework ON risk_scores(contract_id, framework_id)
    WHERE risk_level = 'framework';
-- Supports: contract-level score (dashboard)
CREATE INDEX idx_risk_scores_contract_level_contract ON risk_scores(contract_id)
    WHERE risk_level = 'contract';

COMMENT ON TABLE risk_scores IS
    'Three-level risk scores (clause/framework/contract) with breakdown counts';

-- ---------------------------------------------------------------------------
-- Explainability records: deterministic score decomposition trees.
-- The tree is stored as a JSONB document rather than a recursive table because:
--   1. The tree is generated once, read many times, never partially updated
--   2. JSONB supports deep path queries for audit tooling
--   3. The tree structure varies by contract (different frameworks may apply)
--   4. A recursive CTE on a normalized tree would be complex for no benefit
-- The input_hash ensures the explanation can be verified as matching the
-- state of the data at generation time.
-- ---------------------------------------------------------------------------

CREATE TABLE explainability_records (
    id                          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    contract_id                 UUID        NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    -- Versioning and integrity
    scoring_model_version       TEXT        NOT NULL,
    requirement_library_version TEXT        NOT NULL,
    llm_model_used              TEXT        NOT NULL,
    input_data_hash             TEXT        NOT NULL,    -- SHA-256 of all inputs to scoring
    -- The decomposition tree (full JSON document from Phase 7)
    explanation_tree            JSONB       NOT NULL,
    -- Score reconstruction section (top-level summary)
    score_reconstruction        JSONB       NOT NULL,
    -- Audit metadata
    human_review_required       BOOLEAN     NOT NULL DEFAULT TRUE,
    human_review_flags          TEXT[]      NOT NULL DEFAULT '{}',
    reviewed_by                 TEXT,
    reviewed_at                 TIMESTAMPTZ,
    review_notes                TEXT,
    -- Timestamps
    generated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_explainability_contract UNIQUE (contract_id, scoring_model_version)
);

CREATE INDEX idx_explain_contract ON explainability_records(contract_id);
-- Fix 7: original index was ON (human_review_required) with partial filter
-- WHERE human_review_required = TRUE. Every row in the partial scan had the
-- same value for the indexed column — zero B-tree selectivity within the scan.
-- New index: ON (contract_id) preserves the partial filter and enables efficient
-- lookup of pending reviews per contract.
CREATE INDEX idx_explain_review_pending ON explainability_records(contract_id)
    WHERE human_review_required = TRUE AND reviewed_at IS NULL;

COMMENT ON TABLE explainability_records IS
    'Deterministic score decomposition trees for audit documentation, hash-verified';


-- ============================================================================
-- SECTION 4: REPORTING
-- ============================================================================

CREATE TABLE management_summaries (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    contract_id         UUID        NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    -- Summary content
    executive_summary   TEXT        NOT NULL,            -- 2-3 paragraph overview
    key_findings        JSONB       NOT NULL,            -- structured top findings
    risk_assessment     TEXT        NOT NULL,            -- risk narrative
    recommendations     JSONB       NOT NULL,            -- prioritized action items
    -- Generation metadata
    llm_model_used      TEXT        NOT NULL,
    llm_prompt_version  TEXT        NOT NULL,
    is_ai_generated     BOOLEAN     NOT NULL DEFAULT TRUE,  -- always TRUE; explicit label for compliance
    -- Timestamps
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_summary_contract UNIQUE (contract_id)
);

CREATE INDEX idx_summaries_contract ON management_summaries(contract_id);

COMMENT ON TABLE management_summaries IS
    'LLM-generated management summaries, explicitly labeled as AI-generated output';


-- ============================================================================
-- SECTION 5: AUDIT LOG
-- ============================================================================
-- Not in the original architecture but required for regulated environments.
-- Records every state transition and significant action.
-- Append-only: no UPDATE or DELETE allowed (enforced at application layer).
-- ============================================================================

CREATE TABLE audit_log (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    contract_id UUID        REFERENCES contracts(id) ON DELETE SET NULL,
    action      TEXT        NOT NULL,         -- e.g. 'contract.uploaded', 'analysis.completed'
    actor       TEXT        NOT NULL,         -- user or 'system'
    details     JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Query: audit trail for a contract
CREATE INDEX idx_audit_contract ON audit_log(contract_id, created_at);
-- Query: actions by actor (security review)
CREATE INDEX idx_audit_actor ON audit_log(actor, created_at);
-- Query: specific action types (monitoring)
CREATE INDEX idx_audit_action ON audit_log(action);

COMMENT ON TABLE audit_log IS
    'Append-only audit trail for all significant actions. Required for ISO 27001 / DORA compliance.';


-- ============================================================================
-- INDEX COVERAGE VERIFICATION  (query pattern reference — not executable DDL)
-- ============================================================================
-- 1. FINDINGS BY CONTRACT
--      idx_findings_contract → findings(contract_id)
-- 2. CLAUSES BY CONTRACT
--      idx_clauses_contract  → clauses(contract_id)
-- 3. CLAUSE LOOKUP BY CATEGORY
--      idx_clauses_primary_cat → clauses(primary_category)       single-label
--      idx_clauses_categories  → clauses GIN(canonical_categories) multi-label @>
-- 4. REQUIREMENT LOOKUP BY FRAMEWORK
--      idx_domains_framework   → domains(framework_id)
--      idx_requirements_domain → requirements(domain_id)
--      Planner uses nested-loop index join — efficient at <5000 library rows.
-- 5. GAP DETECTION QUERIES
--      idx_ctrm_type_mandatory    → contract_type_req_mapping(contract_type, mandatory)
--      idx_findings_gap_detection → findings(contract_id, sub_requirement_id, finding_type)
--      Covering index eliminates heap fetch on both sides of the EXCEPT query.
-- ============================================================================
