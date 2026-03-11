"""
Benchmark evaluation for Stage 5 clause-to-SR matching.

Supports offline quality measurement by comparing three matching modes against
a manually curated golden set of clause-to-SR expectations:

  Mode 1 — det_only
      Regex-only deterministic matching; no semantic retrieval, no LLM.

  Mode 2 — semantic_shortlist_candidate_recall
      Measures whether expected sr_ids appear in the merged candidate shortlist
      before LLM validation.  High recall here = retrieval is surfacing the right
      candidates for LLM to validate.  (Recall-only metric; no FP concept.)

  Mode 3 — final
      Full pipeline result after deterministic + semantic + optional LLM pass.

Two scoring policies are computed for modes 1 and 3:

  relaxed — sr_id presence only.  Any non-NO_MATCH result for an expected sr_id
            counts as TP.  Wrong match_type (PARTIAL when DIRECT expected) = TP.

  strict  — sr_id AND match_type must match exactly.  Wrong match_type counts
            as both FP and FN (inflating both error denominators).

No external dependencies.  Safe to import whether LLM is available or not.
Never raises — all public functions return None / empty structures on error.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("stage5.eval")

# Scoring policy descriptions — written verbatim into every metrics artifact
# so that comparisons across runs are self-describing.
SCORING_POLICIES: dict[str, str] = {
    "relaxed": (
        "sr_id presence only. Any non-NO_MATCH result for an expected sr_id "
        "counts as TP. Wrong match_type (e.g. PARTIAL when DIRECT expected) is still TP."
    ),
    "strict": (
        "sr_id AND match_type must match exactly. "
        "Wrong match_type counts as both FP and FN "
        "(one FP for the wrong result + one FN for the missing exact result)."
    ),
}


# ---------------------------------------------------------------------------
# Benchmark file loader
# ---------------------------------------------------------------------------

def load_benchmark(path: str) -> Optional[dict]:
    """
    Load and minimally validate a benchmark JSON file.

    Expected top-level shape::

        {
          "contract_id": "CT-2026-001",
          "clauses": [
            {
              "clause_id": "CL-001",
              "expected_matches": [
                {"sr_id": "SR-ISO27001-01", "expected_match_type": "DIRECT_MATCH"}
              ]
            }
          ]
        }

    Returns the parsed dict, or None on any error (with warning logged).
    Never raises.
    """
    p = Path(path)
    if not p.exists():
        log.warning(f"Benchmark file not found: {path}")
        return None
    try:
        with p.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            log.warning(f"Benchmark must be a JSON object, not a list/scalar: {path}")
            return None
        if "clauses" not in data or not isinstance(data["clauses"], list):
            log.warning(f"Benchmark missing 'clauses' list: {path}")
            return None
        return data
    except (json.JSONDecodeError, OSError) as exc:
        log.warning(f"Benchmark file could not be loaded ({path}): {exc}")
        return None


class BenchmarkIndex:
    """
    Wraps a loaded benchmark dict for O(1) per-clause lookup.

    Parameters
    ----------
    benchmark : dict — as returned by load_benchmark()
    """

    def __init__(self, benchmark: dict) -> None:
        self._contract_id: str = benchmark.get("contract_id", "unknown")
        self._index: dict[str, list[dict]] = {}
        for clause in benchmark.get("clauses", []):
            cid = clause.get("clause_id")
            if cid and isinstance(clause.get("expected_matches"), list):
                self._index[cid] = clause["expected_matches"]

    def get_expected(self, clause_id: str) -> list[dict]:
        """Return expected match list for *clause_id*, or [] if not labeled."""
        return self._index.get(clause_id, [])

    @property
    def contract_id(self) -> str:
        return self._contract_id

    @property
    def clause_ids(self) -> list[str]:
        return list(self._index.keys())

    def __len__(self) -> int:
        return len(self._index)


# ---------------------------------------------------------------------------
# Per-clause comparison
# ---------------------------------------------------------------------------

def _non_no_match(match_types: dict[str, str]) -> dict[str, str]:
    """Filter a {sr_id: match_type} dict to non-NO_MATCH entries."""
    return {sr_id: mt for sr_id, mt in match_types.items() if mt != "NO_MATCH"}


def _pr_clause(
    expected:       list[dict],      # [{"sr_id": ..., "expected_match_type": ...}]
    result_matches: dict[str, str],  # {sr_id: match_type} — non-NO_MATCH results only
    policy:         str,             # "relaxed" | "strict"
) -> dict:
    """
    Compute per-clause TP/FP/FN for one mode under *policy*.
    Returns sr_id lists for full traceability, not just counts.
    """
    expected_map: dict[str, str] = {e["sr_id"]: e["expected_match_type"] for e in expected}
    expected_ids = set(expected_map)
    result_ids   = set(result_matches)
    overlap      = expected_ids & result_ids

    if policy == "relaxed":
        tp_ids         = sorted(overlap)
        fp_ids         = sorted(result_ids - expected_ids)
        fn_ids         = sorted(expected_ids - result_ids)
        wrong_type_ids: list[str] = []
    else:  # strict
        exact = {sr_id for sr_id in overlap
                 if result_matches[sr_id] == expected_map[sr_id]}
        wrong = {sr_id for sr_id in overlap
                 if result_matches[sr_id] != expected_map[sr_id]}
        tp_ids         = sorted(exact)
        fp_ids         = sorted((result_ids - expected_ids) | wrong)
        fn_ids         = sorted((expected_ids - result_ids) | wrong)
        wrong_type_ids = sorted(wrong)

    return {
        "tp_sr_ids":         tp_ids,
        "fp_sr_ids":         fp_ids,
        "fn_sr_ids":         fn_ids,
        "wrong_type_sr_ids": wrong_type_ids,
        "tp": len(tp_ids),
        "fp": len(fp_ids),
        "fn": len(fn_ids),
    }


def _shortlist_coverage_clause(
    expected:  list[dict],
    shortlist: set[str],
) -> dict:
    """
    Measure how many expected sr_ids appear in the merged candidate shortlist.
    Recall-only metric — shortlist is a candidate set, not a match claim.
    """
    expected_ids = {e["sr_id"] for e in expected}
    found        = sorted(expected_ids & shortlist)
    missing      = sorted(expected_ids - shortlist)
    return {
        "found_sr_ids":   found,
        "missing_sr_ids": missing,
        "covered":        len(found),
        "total_expected": len(expected_ids),
    }


def compute_clause_comparison(
    clause_id:         str,
    expected:          list[dict],        # benchmark expected_matches (may be [])
    det_match_types:   dict[str, str],    # {sr_id: match_type} for ALL applicable SRs
    shortlist:         set[str],          # merged candidate shortlist sr_ids
    final_match_types: dict[str, str],    # {sr_id: match_type} for ALL SRs after pipeline
) -> dict:
    """
    Build a complete per-clause comparison dict across all three evaluation modes.

    Parameters
    ----------
    clause_id         : clause identifier
    expected          : benchmark expected_matches list (empty list if clause not labeled)
    det_match_types   : {sr_id: match_type} for ALL applicable SRs from det pass
    shortlist         : merged shortlist of candidate sr_ids (det + semantic)
    final_match_types : {sr_id: match_type} for ALL SRs after LLM validation
    """
    has_benchmark = len(expected) > 0

    det_active   = _non_no_match(det_match_types)
    final_active = _non_no_match(final_match_types)

    det_matches   = [{"sr_id": k, "match_type": v} for k, v in sorted(det_active.items())]
    final_matches = [{"sr_id": k, "match_type": v} for k, v in sorted(final_active.items())]

    # Discrepancies between expected and final result
    discrepancies: list[dict] = []
    if has_benchmark:
        expected_map = {e["sr_id"]: e["expected_match_type"] for e in expected}
        expected_ids = set(expected_map)
        final_ids    = set(final_active)

        for sr_id in sorted(expected_ids - final_ids):
            discrepancies.append({
                "sr_id":               sr_id,
                "type":                "missing_from_final",
                "expected_match_type": expected_map[sr_id],
                "final_match_type":    final_match_types.get(sr_id, "NO_MATCH"),
            })
        for sr_id in sorted(final_ids - expected_ids):
            discrepancies.append({
                "sr_id":               sr_id,
                "type":                "unexpected_in_final",
                "expected_match_type": None,
                "final_match_type":    final_active[sr_id],
            })
        for sr_id in sorted(expected_ids & final_ids):
            if expected_map[sr_id] != final_active[sr_id]:
                discrepancies.append({
                    "sr_id":               sr_id,
                    "type":                "wrong_match_type",
                    "expected_match_type": expected_map[sr_id],
                    "final_match_type":    final_active[sr_id],
                })

    # Per-mode evaluation scores (only when benchmark labels are available)
    evaluation: dict = {}
    if has_benchmark:
        evaluation = {
            "relaxed": {
                "det":       _pr_clause(expected, det_active,   "relaxed"),
                "shortlist": _shortlist_coverage_clause(expected, shortlist),
                "final":     _pr_clause(expected, final_active, "relaxed"),
            },
            "strict": {
                "det":   _pr_clause(expected, det_active,   "strict"),
                "final": _pr_clause(expected, final_active, "strict"),
            },
        }

    return {
        "clause_id":            clause_id,
        "has_benchmark":        has_benchmark,
        "expected_matches":     expected,
        "det_matches":          det_matches,
        "shortlist_candidates": sorted(shortlist),
        "final_matches":        final_matches,
        "discrepancies":        discrepancies,
        "evaluation":           evaluation,
    }


# ---------------------------------------------------------------------------
# Run-level metric aggregation
# ---------------------------------------------------------------------------

def _aggregate_pr(
    clause_comparisons: list[dict],
    mode:               str,    # "det" | "final"
    policy:             str,    # "relaxed" | "strict"
) -> dict:
    """Aggregate TP/FP/FN across all labeled clauses, compute P/R/F1."""
    total_tp = total_fp = total_fn = 0
    for comp in clause_comparisons:
        if not comp["has_benchmark"]:
            continue
        ev = comp["evaluation"].get(policy, {}).get(mode, {})
        total_tp += ev.get("tp", 0)
        total_fp += ev.get("fp", 0)
        total_fn += ev.get("fn", 0)

    prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else None
    rec  = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else None
    f1   = (2 * prec * rec / (prec + rec)
            if prec is not None and rec is not None and (prec + rec) > 0
            else None)

    return {
        "precision": round(prec, 4) if prec is not None else None,
        "recall":    round(rec,  4) if rec  is not None else None,
        "f1":        round(f1,   4) if f1   is not None else None,
        "tp": total_tp,
        "fp": total_fp,
        "fn": total_fn,
    }


def _aggregate_shortlist_recall(clause_comparisons: list[dict]) -> dict:
    """
    Aggregate shortlist candidate recall across all labeled clauses.
    Always relaxed (sr_id presence only); no FP concept for candidate sets.
    """
    total_covered  = 0
    total_expected = 0
    for comp in clause_comparisons:
        if not comp["has_benchmark"]:
            continue
        cov = comp["evaluation"].get("relaxed", {}).get("shortlist", {})
        total_covered  += cov.get("covered",        0)
        total_expected += cov.get("total_expected",  0)

    recall = total_covered / total_expected if total_expected > 0 else None
    return {
        "recall":         round(recall, 4) if recall is not None else None,
        "covered":        total_covered,
        "total_expected": total_expected,
        "note": (
            "Measures whether expected sr_ids appear in the merged candidate shortlist "
            "before LLM validation. High recall = semantic retrieval surfaces the right "
            "candidates for LLM to validate."
        ),
    }


def compute_benchmark_metrics(
    clause_comparisons: list[dict],
    run_meta:           dict,
) -> dict:
    """
    Compute run-level precision/recall/F1 for all three modes × both policies.

    Parameters
    ----------
    clause_comparisons : list of dicts from compute_clause_comparison()
    run_meta           : reproducibility metadata dict (written verbatim to artifact)
    """
    total    = len(clause_comparisons)
    labeled  = sum(1 for c in clause_comparisons if c["has_benchmark"])
    unlabeled = total - labeled

    return {
        "run_meta":         run_meta,
        "scoring_policies": SCORING_POLICIES,
        "clause_coverage": {
            "total":     total,
            "labeled":   labeled,
            "unlabeled": unlabeled,
            "fraction":  round(labeled / total, 4) if total > 0 else None,
        },
        "modes": {
            "det_only": {
                "description": (
                    "Regex-only deterministic matching; "
                    "no semantic retrieval, no LLM."
                ),
                "relaxed": _aggregate_pr(clause_comparisons, "det",   "relaxed"),
                "strict":  _aggregate_pr(clause_comparisons, "det",   "strict"),
            },
            "semantic_shortlist_candidate_recall": {
                "description": (
                    "Recall of expected sr_ids in the merged candidate shortlist "
                    "(deterministic + semantic retrieval, before LLM). "
                    "Measures whether retrieval surfaces the right candidates."
                ),
                **_aggregate_shortlist_recall(clause_comparisons),
            },
            "final": {
                "description": (
                    "Full pipeline result: deterministic + semantic retrieval "
                    "+ LLM validation (or deterministic + semantic if LLM disabled)."
                ),
                "relaxed": _aggregate_pr(clause_comparisons, "final", "relaxed"),
                "strict":  _aggregate_pr(clause_comparisons, "final", "strict"),
            },
        },
    }


# ---------------------------------------------------------------------------
# Artifact writer
# ---------------------------------------------------------------------------

def write_eval_artifacts(
    comparison_data: list[dict],
    metrics:         dict,
    eval_dir:        str,
) -> None:
    """
    Write Stage 5 benchmark evaluation artifacts to *eval_dir*.

    Files written
    -------------
    benchmark_comparison_stage5.json  — per-clause det / shortlist / final comparison
    benchmark_metrics_stage5.json     — run-level P/R/F1 per mode × policy
    """
    p = Path(eval_dir)
    p.mkdir(parents=True, exist_ok=True)

    comp_path    = p / "benchmark_comparison_stage5.json"
    metrics_path = p / "benchmark_metrics_stage5.json"

    with comp_path.open("w", encoding="utf-8") as fh:
        json.dump(comparison_data, fh, indent=2, ensure_ascii=False)
    with metrics_path.open("w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2, ensure_ascii=False)

    labeled = metrics["clause_coverage"]["labeled"]
    log.info(f"Eval artifacts → {eval_dir}/")
    log.info(
        f"  benchmark_comparison_stage5.json  "
        f"({len(comparison_data)} clauses, {labeled} labeled)"
    )
    log.info("  benchmark_metrics_stage5.json")
    _log_metrics_summary(metrics)


def _log_metrics_summary(metrics: dict) -> None:
    """Log a compact summary of key metrics to INFO."""
    modes = metrics.get("modes", {})
    for name, data in [
        ("det_only", modes.get("det_only", {})),
        ("final",    modes.get("final",    {})),
    ]:
        r = data.get("relaxed", {})
        log.info(
            f"  [{name:12s}] (relaxed)  "
            f"P={r.get('precision')!s:6}  R={r.get('recall')!s:6}  "
            f"F1={r.get('f1')!s:6}  "
            f"TP={r.get('tp', 0)}  FP={r.get('fp', 0)}  FN={r.get('fn', 0)}"
        )
    sl = modes.get("semantic_shortlist_candidate_recall", {})
    log.info(
        f"  [shortlist    ] candidate_recall={sl.get('recall')!s:6}  "
        f"covered={sl.get('covered', 0)}/{sl.get('total_expected', 0)}"
    )
