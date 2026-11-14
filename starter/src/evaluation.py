"""Evaluate retrieval traces (Hit@1, Evidence Hit@3, metadata checks) without faking human labels."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "")).strip()


def _gold_candidates(question: dict[str, Any]) -> list[tuple[str, int, str]]:
    cands = [
        (
            str(question["gold_source_id"]),
            int(question["gold_page"]),
            str(question["evidence_quote"]),
        )
    ]
    for alt in question.get("alternative_gold") or []:
        cands.append(
            (
                str(alt["gold_source_id"]),
                int(alt["gold_page"]),
                str(alt["evidence_quote"]),
            )
        )
    return cands


def _check_filter_match(hit: dict[str, Any], flt: dict[str, Any]) -> bool:
    meta = hit.get("metadata") or {}
    for key, expected in flt.items():
        actual = meta.get(key, hit.get(key))
        if actual != expected:
            return False
    return True


def evaluate_query(
    question: dict[str, Any],
    hits: list[dict[str, Any]],
    applied_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check source/page and exact normalized evidence substring in top-k hits."""
    golds = _gold_candidates(question)
    hit_traces: list[dict[str, Any]] = []

    hit_at_1 = False
    hit_at_3 = False
    page_hit_at_3 = False
    meta_valid_count = 0

    for rank, hit in enumerate(hits[:3], start=1):
        h_doc = str(hit.get("document_id", ""))
        h_page = int(hit.get("page", -1))
        h_flat = _flat(str(hit.get("text", "")))
        h_meta = hit.get("metadata") or {}

        page_match = any(h_doc == g_doc and h_page == g_page for g_doc, g_page, _ in golds)
        evidence_match = any(
            h_doc == g_doc and h_page == g_page and _flat(g_quote) in h_flat
            for g_doc, g_page, g_quote in golds
        )
        meta_complete = bool(
            hit.get("source")
            and hit.get("page") is not None
            and h_meta.get("year") is not None
            and h_meta.get("category")
        )
        if meta_complete:
            meta_valid_count += 1

        if rank == 1 and evidence_match:
            hit_at_1 = True
        if evidence_match:
            hit_at_3 = True
        if page_match:
            page_hit_at_3 = True

        hit_traces.append(
            {
                "rank": rank,
                "chunk_id": hit.get("chunk_id"),
                "document_id": h_doc,
                "source": hit.get("source"),
                "page": h_page,
                "score": hit.get("score"),
                "metadata": h_meta,
                "page_match": page_match,
                "evidence_match": evidence_match,
                "metadata_complete": meta_complete,
                "text": hit.get("text"),
            }
        )

    # Diagnostic check: if fixed-size windows split an evidence quote across adjacent chunks on the gold page
    multi_chunk_hit_at_3 = hit_at_3
    if not multi_chunk_hit_at_3:
        for g_doc, g_page, g_quote in golds:
            combined = " ".join(
                _flat(str(h.get("text", "")))
                for h in hits[:3]
                if str(h.get("document_id", "")) == g_doc and int(h.get("page", -1)) == g_page
            )
            if _flat(g_quote) in combined:
                multi_chunk_hit_at_3 = True
                break

    q_filter = question.get("filter")
    if q_filter:
        filter_compliant = bool(hits[:3]) and all(
            _check_filter_match(h, q_filter) for h in hits[:3]
        )
    else:
        filter_compliant = None

    return {
        "id": question["id"],
        "split": question["split"],
        "type": question["type"],
        "question": question["question"],
        "expected_answer": question["expected_answer"],
        "gold_source_id": question["gold_source_id"],
        "gold_page": int(question["gold_page"]),
        "evidence_quote": question["evidence_quote"],
        "question_filter": q_filter,
        "applied_filter": applied_filter,
        "hit_at_1": hit_at_1,
        "hit_at_3": hit_at_3,
        "page_hit_at_3": page_hit_at_3,
        "multi_chunk_evidence_hit_at_3": multi_chunk_hit_at_3,
        "meta_valid_count": meta_valid_count,
        "meta_total_count": len(hits[:3]),
        "filter_compliant": filter_compliant,
        "hits": hit_traces,
    }


def _aggregate_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(group)
    if n == 0:
        return {
            "n": 0,
            "hit1_count": 0,
            "hit1_rate": 0.0,
            "hit3_count": 0,
            "hit3_rate": 0.0,
            "page_hit3_count": 0,
            "multi_chunk_hit3_count": 0,
            "metadata_valid_hits": 0,
            "metadata_total_hits": 0,
            "filter_compliant_queries": 0,
            "filter_total_queries": 0,
        }

    hit1 = sum(1 for t in group if t["hit_at_1"])
    hit3 = sum(1 for t in group if t["hit_at_3"])
    page_hit3 = sum(1 for t in group if t["page_hit_at_3"])
    multi_hit3 = sum(1 for t in group if t["multi_chunk_evidence_hit_at_3"])
    meta_valid = sum(int(t["meta_valid_count"]) for t in group)
    meta_total = sum(int(t["meta_total_count"]) for t in group)
    flt_group = [t for t in group if t["filter_compliant"] is not None]
    flt_ok = sum(1 for t in flt_group if t["filter_compliant"])

    return {
        "n": n,
        "hit1_count": hit1,
        "hit1_rate": round(hit1 / n, 4),
        "hit3_count": hit3,
        "hit3_rate": round(hit3 / n, 4),
        "page_hit3_count": page_hit3,
        "multi_chunk_hit3_count": multi_hit3,
        "metadata_valid_hits": meta_valid,
        "metadata_total_hits": meta_total,
        "filter_compliant_queries": flt_ok,
        "filter_total_queries": len(flt_group),
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Hit@1 and Evidence Hit@3 by strategy and dev/test split."""
    strategies = sorted({str(t["strategy"]) for t in traces})
    summary: dict[str, Any] = {}

    for strat in strategies:
        strat_traces = [t for t in traces if t["strategy"] == strat]
        summary[strat] = {
            "dev": _aggregate_group([t for t in strat_traces if t["split"] == "dev"]),
            "test": _aggregate_group([t for t in strat_traces if t["split"] == "test"]),
            "all": _aggregate_group(strat_traces),
        }
    return summary
