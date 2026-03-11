"""
Semantic candidate retrieval for Stage 5 clause-to-SR matching.

Implements an in-process TF-IDF corpus for scoring Security Requirements (SRs)
against clause text.  No external vector database or network calls required.

Design:
  - SRCorpus is built once from the SR catalog (title + match_patterns).
  - Each SR gets a pre-computed TF-IDF vector at construction time.
  - query() computes a TF-IDF vector for the clause text at runtime, then
    returns the top-k most similar SRs by cosine similarity.
  - filter_sr_ids limits scoring to an applicable subset without rebuilding.

Retrieval corpus construction:
  Each SR retrieval document is built from:
    title (repeated for upweighting) + description + cleaned match_patterns +
    retrieval_synonyms (optional per-SR list)

  retrieval_synonyms extend the vocabulary with domain language variants,
  regulatory synonyms, and common paraphrases that appear in contract clauses
  but are not captured by deterministic patterns.  Examples:
    SR-DORA-02: "supervisory body" / "supervisory bodies" →  "competent authorities"
    SR-GDPR-03: "European Economic Area" → "third country transfer"

TF-IDF limitation — known synonym gaps:
  TF-IDF is a bag-of-words model.  It scores documents by shared token overlap.
  When a clause uses a synonym that does not appear in the SR retrieval document,
  cosine similarity will be near zero even if the clause is semantically relevant.

  Benchmark-confirmed cases (as of 2026-03):
    CL-011: "supervisory bodies" ≠ "competent authorities" (SR-DORA-02)
      - Before synonym addition: SR-DORA-02 missing from shortlist.
      - Fix: add "supervisory body/bodies" to SR-DORA-02 retrieval_synonyms.

    CL-010: "countries outside the European Economic Area" ≠ "third country transfer"
      - Before synonym addition: SR-GDPR-03 borderline in shortlist.
      - Fix: add "European Economic Area", "cross-border" etc. to retrieval_synonyms.

  Embeddings would close these gaps automatically, but are intentionally excluded
  from this architecture (dependency-free, offline, deterministic).  retrieval_synonyms
  are the approved mechanism for bridging these synonym gaps without adding deps.

Thread safety: SRCorpus is read-only after __init__; safe to share across threads.
Tenant safety: no shared mutable state; each caller supplies its own clause text.
"""
from __future__ import annotations

import math
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

_REGEX_META = re.compile(r'[\\|?.+*^$\[\](){}]')
_TOKEN_RE   = re.compile(r'\b[a-z]{2,}\b')

_STOP_WORDS: frozenset[str] = frozenset({
    "the", "an", "and", "or", "of", "to", "in", "for", "is", "are",
    "be", "by", "as", "at", "on", "with", "this", "that", "from",
    "it", "its", "any", "all", "may", "must", "shall", "should",
    "will", "not", "no", "have", "has", "been", "their", "which",
    "each", "per", "when", "where", "more", "than",
})


def _clean_pattern(pattern: str) -> str:
    """
    Convert a regex pattern string to plain retrieval text.

    Removes regex metacharacters and common anchors, preserving the
    meaningful keyword tokens (e.g. 'iso.{0,5}27001' → 'iso 27001').
    """
    text = _REGEX_META.sub(" ", pattern)
    # Remove numeric quantifiers left over from {0,5} removal
    text = re.sub(r'\d+', ' ', text)
    return text.strip()


def _tokenize(text: str) -> list[str]:
    """Lowercase word tokenizer that strips stop words and short tokens."""
    tokens = _TOKEN_RE.findall(text.lower())
    return [t for t in tokens if t not in _STOP_WORDS]


# ---------------------------------------------------------------------------
# TF-IDF corpus
# ---------------------------------------------------------------------------

class SRCorpus:
    """
    Pre-computed TF-IDF corpus built from an SR catalog.

    Parameters
    ----------
    sr_catalog : list[dict]
        The SR catalog entries.  Each entry must have at least 'id', 'title',
        and 'match_patterns'.  Optional: 'description'.

    Attributes (read-only after __init__)
    --------------------------------------
    corpus_size : int   — number of SRs indexed
    vocab_size  : int   — number of unique terms in the vocabulary
    """

    def __init__(self, sr_catalog: list[dict]) -> None:
        self._sr_catalog = sr_catalog
        self._sr_ids: list[str] = [sr["id"] for sr in sr_catalog]

        # Build retrieval document for each SR
        docs = [self._build_retrieval_text(sr) for sr in sr_catalog]

        # Tokenize each document
        tokenized: list[list[str]] = [_tokenize(doc) for doc in docs]

        # Compute IDF (smoothed: log((N+1)/(df+1)) + 1)
        N = len(tokenized)
        df: dict[str, int] = {}
        for tokens in tokenized:
            for tok in set(tokens):
                df[tok] = df.get(tok, 0) + 1

        self._idf: dict[str, float] = {
            tok: math.log((N + 1) / (count + 1)) + 1.0
            for tok, count in df.items()
        }

        # Pre-compute and store TF-IDF vector for every SR
        self._sr_vectors: list[dict[str, float]] = [
            self._tfidf_vector(tokens) for tokens in tokenized
        ]

        self.corpus_size = len(sr_catalog)
        self.vocab_size  = len(self._idf)

    # ── Private helpers ────────────────────────────────────────────────────

    @staticmethod
    def _build_retrieval_text(sr: dict) -> str:
        """
        Combine SR fields into a single retrieval document string.

        Uses: title (repeated for upweighting), description (if present),
        cleaned match_patterns, and optional retrieval_synonyms.

        retrieval_synonyms are plain-text phrases added to the retrieval
        document to improve recall for clauses that use regulatory synonyms
        or domain language variants not covered by match_patterns.
        They are appended verbatim (no regex cleaning needed).

        Example: SR-DORA-02 adds "supervisory body", "supervisory bodies"
        so that a clause referencing "supervisory bodies" scores high for
        SR-DORA-02 even though the patterns use "competent authorit".
        """
        parts: list[str] = [
            sr.get("title", ""),
            sr.get("title", ""),          # deliberate repeat: title upweighted
            sr.get("description", ""),
        ]
        for pat in sr.get("match_patterns", []):
            parts.append(_clean_pattern(pat))
        # Append synonym extensions: plain text, no cleaning required.
        for synonym in sr.get("retrieval_synonyms", []):
            parts.append(synonym)
        return " ".join(p for p in parts if p)

    def _tfidf_vector(self, tokens: list[str]) -> dict[str, float]:
        """Compute a normalised TF-IDF vector (L2) from a token list."""
        if not tokens:
            return {}
        n = len(tokens)
        # Term frequency (raw count / document length)
        tf: dict[str, float] = {}
        for tok in tokens:
            tf[tok] = tf.get(tok, 0.0) + 1.0 / n

        # Multiply by IDF (unknown terms get idf=0, so they're silently skipped)
        vec: dict[str, float] = {
            tok: tf_val * self._idf[tok]
            for tok, tf_val in tf.items()
            if tok in self._idf
        }

        # L2 normalise
        norm = math.sqrt(sum(v * v for v in vec.values()))
        if norm > 0:
            vec = {tok: v / norm for tok, v in vec.items()}
        return vec

    @staticmethod
    def _cosine(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
        """Dot product of two L2-normalised vectors (= cosine similarity)."""
        return sum(vec_a.get(tok, 0.0) * val for tok, val in vec_b.items())

    # ── Public API ─────────────────────────────────────────────────────────

    def query(
        self,
        clause_text:    str,
        top_k:          int            = 5,
        min_score:      float          = 0.15,
        filter_sr_ids:  Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Return the top-k SRs most semantically similar to *clause_text*.

        Parameters
        ----------
        clause_text   : Raw clause text (full, not truncated).
        top_k         : Maximum number of results to return.
        min_score     : Minimum cosine similarity threshold; results below
                        this are discarded.
        filter_sr_ids : If provided, only score SRs whose id appears in
                        this list.  Allows cheap per-run applicability
                        filtering without rebuilding the corpus.

        Returns
        -------
        list of dicts, sorted by score descending:
            {"sr_id": str, "score": float, "rank": int}
        """
        query_tokens = _tokenize(clause_text)
        if not query_tokens:
            return []

        query_vec = self._tfidf_vector(query_tokens)
        if not query_vec:
            return []

        # Build a set for O(1) membership tests
        filter_set: Optional[set[str]] = (
            set(filter_sr_ids) if filter_sr_ids is not None else None
        )

        scored: list[tuple[float, str]] = []
        for sr_id, sr_vec in zip(self._sr_ids, self._sr_vectors):
            if filter_set is not None and sr_id not in filter_set:
                continue
            score = self._cosine(query_vec, sr_vec)
            if score >= min_score:
                scored.append((score, sr_id))

        scored.sort(reverse=True)
        results: list[dict] = []
        for rank, (score, sr_id) in enumerate(scored[:top_k], start=1):
            results.append({"sr_id": sr_id, "score": round(score, 4), "rank": rank})
        return results
