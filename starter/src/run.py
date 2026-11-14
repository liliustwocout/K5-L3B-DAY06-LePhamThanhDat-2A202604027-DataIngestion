"""Day 06 Data Ingestion Engineering pipeline orchestration and benchmark runner."""
from __future__ import annotations

import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import MyEmbedder
from .evaluation import evaluate_query, summarize
from .ingestion import load_corpus_from_manifest
from .models import Chunk, DocumentPage
from .store import PgVectorStore

STARTER_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = STARTER_DIR.parent

STRATEGY_CONFIGS: list[dict[str, Any]] = [
    {
        "strategy": "A",
        "chunking": "fixed_size",
        "chunk_size": 500,
        "overlap": 50,
        "use_filter": False,
        "description": "Fixed-size 500-char windows with 50-char overlap, no metadata filter.",
    },
    {
        "strategy": "B",
        "chunking": "by_paragraph",
        "chunk_size": 1200,
        "overlap": 0,
        "use_filter": False,
        "description": "Paragraph-aware chunking up to 1200 chars, no metadata filter.",
    },
    {
        "strategy": "C",
        "chunking": "by_paragraph",
        "chunk_size": 1200,
        "overlap": 0,
        "use_filter": True,
        "description": "Paragraph-aware chunking up to 1200 chars + SQL metadata filter when query specifies filter.",
    },
]

# Pre-selected 10 source locations (first 4/3/3 valid pages per document) prior to inspecting scores.
COHERENCE_SAMPLE_LOCATIONS: list[tuple[str, int]] = [
    ("nist-ir-8312", 8),
    ("nist-ir-8312", 9),
    ("nist-ir-8312", 10),
    ("nist-ir-8312", 11),
    ("nist-sp-1270", 10),
    ("nist-sp-1270", 11),
    ("nist-sp-1270", 12),
    ("nist-sp-800-218a", 9),
    ("nist-sp-800-218a", 10),
    ("nist-sp-800-218a", 11),
]


def _build_chunks(pages: list[DocumentPage], cfg: dict[str, Any]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page in pages:
        if cfg["chunking"] == "fixed_size":
            chunks.extend(fixed_size(page, size=int(cfg["chunk_size"]), overlap=int(cfg["overlap"])))
        elif cfg["chunking"] == "by_paragraph":
            chunks.extend(by_paragraph(page, max_size=int(cfg["chunk_size"])))
        else:
            raise ValueError(f"Unsupported chunking method: {cfg['chunking']}")
    return chunks


def _chunk_length_stats(chunks: list[Chunk]) -> dict[str, Any]:
    lengths = sorted(len(c.text) for c in chunks)
    if not lengths:
        return {"count": 0, "total_chars": 0, "min": 0, "p50": 0, "mean": 0.0, "p95": 0, "max": 0}
    return {
        "count": len(lengths),
        "total_chars": sum(lengths),
        "min": lengths[0],
        "p50": lengths[len(lengths) // 2],
        "mean": round(statistics.mean(lengths), 1),
        "p95": lengths[min(len(lengths) - 1, int(0.95 * len(lengths)))],
        "max": lengths[-1],
    }


def _verify_reingestion_idempotency(
    store: PgVectorStore,
    strategy: str,
    chunks: list[Chunk],
    vectors: list[list[float]],
) -> dict[str, Any]:
    """Prove repeated upsert does not duplicate rows and obsolete chunks are pruned."""
    count_after_first = store.count_chunks(strategy)
    reupsert_stats = store.upsert(strategy, chunks, vectors)
    count_after_second = store.count_chunks(strategy)

    # Verify obsolete chunk cleanup using an isolated temporary strategy key.
    temp_strategy = "_idempotency_probe"
    store.delete_document(temp_strategy, "probe-doc")
    c1 = Chunk("probe-doc:p001:0", "probe-doc", "probe.pdf", 1, "Chunk one", {"year": 2024, "category": "probe"})
    c2 = Chunk("probe-doc:p001:1", "probe-doc", "probe.pdf", 1, "Chunk two", {"year": 2024, "category": "probe"})
    store.upsert(temp_strategy, [c1, c2], [vectors[0], vectors[1]])
    before_prune = store.count_chunks(temp_strategy)
    prune_stats = store.upsert(temp_strategy, [c1], [vectors[0]])
    after_prune = store.count_chunks(temp_strategy)
    store.delete_document(temp_strategy, "probe-doc")

    return {
        "strategy_checked": strategy,
        "count_after_first_upsert": count_after_first,
        "count_after_second_upsert": count_after_second,
        "no_duplicates_verified": count_after_first == count_after_second == len(chunks),
        "second_upsert_stats": reupsert_stats,
        "obsolete_cleanup_probe": {
            "before_prune_count": before_prune,
            "after_prune_count": after_prune,
            "deleted_obsolete": prune_stats["deleted_obsolete"],
            "obsolete_pruned_verified": before_prune == 2 and after_prune == 1 and prune_stats["deleted_obsolete"] == 1,
        },
    }


def _write_json_to_both(rel_name: str, payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for base in (STARTER_DIR / "results", ROOT_DIR / "results"):
        base.mkdir(parents=True, exist_ok=True)
        (base / rel_name).write_text(text, encoding="utf-8")


def main() -> None:
    load_dotenv(STARTER_DIR / ".env")
    database_url = os.getenv("DATABASE_URL", "").strip()
    model_name = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001").strip() or "gemini-embedding-001"

    manifest_path = ROOT_DIR / "data" / "manifest.json"
    benchmark_path = ROOT_DIR / "benchmark" / "questions.json"

    pages, ingestion_log = load_corpus_from_manifest(manifest_path, ROOT_DIR)
    if ingestion_log["total_valid_content_pages"] < 30:
        raise RuntimeError(
            f"Corpus has only {ingestion_log['total_valid_content_pages']} valid pages (< 30 required)."
        )

    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    questions: list[dict[str, Any]] = benchmark["questions"]
    if len(questions) < 20:
        raise RuntimeError(f"Benchmark has only {len(questions)} questions (< 20 required).")

    embedder = MyEmbedder(
        model_name=model_name,
        dimensions=768,
        batch_size=30,
        max_rpm=90,
        cache_path=STARTER_DIR / "results" / ".embedding_cache.json",
    )
    store = PgVectorStore(database_url=database_url, dimensions=embedder.dimensions)
    store.create_schema()

    # Embed all unique questions once (identical query vectors across A, B, C).
    t_q0 = time.perf_counter()
    query_vectors = {q["id"]: embedder.embed_query(q["question"]) for q in questions}
    query_embed_seconds = round(time.perf_counter() - t_q0, 3)

    strategy_stats: dict[str, Any] = {}
    all_traces: list[dict[str, Any]] = []
    chunks_by_strategy: dict[str, list[Chunk]] = {}
    idempotency_report: dict[str, Any] | None = None

    for cfg in STRATEGY_CONFIGS:
        strat = cfg["strategy"]
        t_start = time.perf_counter()

        stats_before = dict(embedder.stats)
        chunks = _build_chunks(pages, cfg)
        chunks_by_strategy[strat] = chunks
        t_chunk = time.perf_counter()

        vectors = embedder.embed_documents([c.text for c in chunks])
        t_embed = time.perf_counter()

        upsert_info = store.upsert(strat, chunks, vectors)
        t_upsert = time.perf_counter()

        if idempotency_report is None:
            idempotency_report = _verify_reingestion_idempotency(store, strat, chunks, vectors)

        t_query_start = time.perf_counter()
        for q in questions:
            applied_filter = q["filter"] if (cfg["use_filter"] and q.get("filter")) else None
            hits = store.search(
                strategy=strat,
                query_vector=query_vectors[q["id"]],
                top_k=3,
                filters=applied_filter,
            )
            trace = evaluate_query(q, hits, applied_filter=applied_filter)
            trace["strategy"] = strat
            all_traces.append(trace)
        t_query_end = time.perf_counter()

        stats_after = dict(embedder.stats)
        strategy_stats[strat] = {
            "config": cfg,
            "chunk_stats": _chunk_length_stats(chunks),
            "upsert_info": upsert_info,
            "stored_row_count": store.count_chunks(strat),
            "timing_seconds": {
                "chunking": round(t_chunk - t_start, 4),
                "embedding": round(t_embed - t_chunk, 4),
                "db_upsert": round(t_upsert - t_embed, 4),
                "ingest_total": round(t_upsert - t_start, 4),
                "retrieval_24q": round(t_query_end - t_query_start, 4),
            },
            "embedding_calls_delta": int(stats_after["api_calls"]) - int(stats_before["api_calls"]),
            "embedding_texts_api_delta": int(stats_after["api_texts_embedded"]) - int(stats_before["api_texts_embedded"]),
            "embedding_cache_hits_delta": int(stats_after["cache_hits"]) - int(stats_before["cache_hits"]),
        }

    retrieval_summary = summarize(all_traces)
    metrics_payload = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "embedding_model": embedder.model_name,
        "embedding_dimensions": embedder.dimensions,
        "vector_store": "PostgreSQL 16 + pgvector 0.8.7 (exact cosine distance <=>)",
        "query_embed_seconds": query_embed_seconds,
        "embedder_cumulative_stats": embedder.stats,
        "idempotency_check": idempotency_report,
        "strategy_stats": strategy_stats,
        "retrieval_metrics": retrieval_summary,
    }

    # Prepare manual assessment sample sheets (raw extracts only; never pre-filled fake labels).
    coherence_samples: list[dict[str, Any]] = []
    for loc_idx, (doc_id, page_no) in enumerate(COHERENCE_SAMPLE_LOCATIONS, start=1):
        entry: dict[str, Any] = {
            "sample_id": f"coh_{loc_idx:02d}",
            "document_id": doc_id,
            "page": page_no,
            "strategies": {},
        }
        for strat, chunks in chunks_by_strategy.items():
            page_chunks = [c for c in chunks if c.document_id == doc_id and c.page == page_no]
            chosen = page_chunks[0] if page_chunks else None
            entry["strategies"][strat] = (
                {
                    "chunk_id": chosen.chunk_id,
                    "chunk_char_len": len(chosen.text),
                    "total_chunks_on_page": len(page_chunks),
                    "text": chosen.text,
                    "manual_score_0_to_2": None,
                    "manual_reason": "",
                }
                if chosen
                else None
            )
        coherence_samples.append(entry)

    test_traces = [t for t in all_traces if t["split"] == "test"]
    metadata_samples = [
        {
            "strategy": t["strategy"],
            "question_id": t["id"],
            "gold_source_id": t["gold_source_id"],
            "gold_page": t["gold_page"],
            "question_filter": t["question_filter"],
            "applied_filter": t["applied_filter"],
            "filter_compliant": t["filter_compliant"],
            "hits": [
                {
                    "rank": h["rank"],
                    "chunk_id": h["chunk_id"],
                    "source": h["source"],
                    "page": h["page"],
                    "year": h["metadata"].get("year"),
                    "category": h["metadata"].get("category"),
                    "section": h["metadata"].get("section"),
                    "metadata_complete": h["metadata_complete"],
                    "verified_accurate": None,
                    "error_note": "",
                }
                for h in t["hits"]
            ],
        }
        for t in test_traces
    ]

    grounding_samples = [
        {
            "strategy": t["strategy"],
            "question_id": t["id"],
            "question": t["question"],
            "expected_answer": t["expected_answer"],
            "gold_source_id": t["gold_source_id"],
            "gold_page": t["gold_page"],
            "evidence_quote": t["evidence_quote"],
            "auto_evidence_hit_at_3": t["hit_at_3"],
            "top_3_texts": [
                {
                    "rank": h["rank"],
                    "chunk_id": h["chunk_id"],
                    "source": h["source"],
                    "page": h["page"],
                    "score": h["score"],
                    "text": h["text"],
                }
                for h in t["hits"]
            ],
            "manual_grounding_0_to_2": None,
            "manual_reason": "",
        }
        for t in test_traces
    ]

    _write_json_to_both("ingestion_log.json", ingestion_log)
    _write_json_to_both("traces_all.json", all_traces)
    _write_json_to_both("metrics_summary.json", metrics_payload)
    _write_json_to_both("coherence_audit_samples.json", coherence_samples)
    _write_json_to_both("metadata_audit_samples.json", metadata_samples)
    _write_json_to_both("grounding_audit_samples.json", grounding_samples)

    print("=== Day 06 Pipeline Complete ===")
    print(
        f"Corpus: {ingestion_log['total_valid_content_pages']} valid pages / "
        f"{ingestion_log['total_valid_normalized_chars']} chars"
    )
    print(
        f"Idempotency verified: {idempotency_report['no_duplicates_verified']} | "
        f"Obsolete pruned: {idempotency_report['obsolete_cleanup_probe']['obsolete_pruned_verified']}"
    )
    for strat in ("A", "B", "C"):
        st = strategy_stats[strat]
        dev_m = retrieval_summary[strat]["dev"]
        test_m = retrieval_summary[strat]["test"]
        print(
            f"Strategy {strat} | chunks={st['chunk_stats']['count']} "
            f"| ingest={st['timing_seconds']['ingest_total']}s "
            f"| dev Hit@1={dev_m['hit1_count']}/{dev_m['n']} Hit@3={dev_m['hit3_count']}/{dev_m['n']} "
            f"| test Hit@1={test_m['hit1_count']}/{test_m['n']} Hit@3={test_m['hit3_count']}/{test_m['n']}"
        )


if __name__ == "__main__":
    main()
