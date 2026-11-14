"""PostgreSQL + pgvector storage, idempotent upsert, and filtered cosine search."""
from __future__ import annotations

import json
from typing import Any

import psycopg

from .models import Chunk

ALLOWED_FILTER_COLUMNS = {
    "document_id": "document_id",
    "source": "source",
    "page": "page",
    "section": "section",
    "year": "year",
    "category": "category",
}


def _to_pgvector(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in vec) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("database_url must not be empty.")
        if dimensions <= 0:
            raise ValueError(f"dimensions must be > 0, got {dimensions}")
        self.database_url = database_url
        self.dimensions = int(dimensions)

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url, connect_timeout=10)

    def create_schema(self) -> None:
        """Ensure vector extension and rag_chunks table + indexes exist."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS rag_chunks (
                        strategy TEXT NOT NULL,
                        chunk_id TEXT NOT NULL,
                        document_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        page INTEGER NOT NULL,
                        section TEXT,
                        year INTEGER,
                        category TEXT,
                        text TEXT NOT NULL,
                        metadata JSONB NOT NULL,
                        embedding vector({self.dimensions}) NOT NULL,
                        PRIMARY KEY (strategy, chunk_id)
                    );
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_rag_chunks_strategy_doc "
                    "ON rag_chunks (strategy, document_id);"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_rag_chunks_strategy_filters "
                    "ON rag_chunks (strategy, year, category);"
                )
            conn.commit()

    def count_chunks(self, strategy: str) -> int:
        """Return number of stored chunks for a strategy."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM rag_chunks WHERE strategy = %s;",
                    (strategy,),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0

    def upsert(
        self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]
    ) -> dict[str, int]:
        """Validate vectors and write chunks idempotently, removing obsolete chunks."""
        if len(chunks) != len(vectors):
            raise ValueError(
                f"chunks ({len(chunks)}) and vectors ({len(vectors)}) length mismatch."
            )
        for idx, vec in enumerate(vectors):
            if len(vec) != self.dimensions:
                raise ValueError(
                    f"Vector {idx} has dimension {len(vec)}, expected {self.dimensions}."
                )

        if not chunks:
            return {"deleted_obsolete": 0, "upserted": 0}

        ids_by_doc: dict[str, list[str]] = {}
        rows: list[tuple[Any, ...]] = []

        for chunk, vec in zip(chunks, vectors):
            ids_by_doc.setdefault(chunk.document_id, []).append(chunk.chunk_id)
            meta = dict(chunk.metadata)
            meta["document_id"] = chunk.document_id
            meta["source"] = chunk.source
            meta["page"] = int(chunk.page)

            year_val = meta.get("year")
            year_int = int(year_val) if year_val is not None else None
            section_val = str(meta.get("section")) if meta.get("section") is not None else None
            category_val = str(meta.get("category")) if meta.get("category") is not None else None

            rows.append(
                (
                    strategy,
                    chunk.chunk_id,
                    chunk.document_id,
                    chunk.source,
                    int(chunk.page),
                    section_val,
                    year_int,
                    category_val,
                    chunk.text,
                    json.dumps(meta, ensure_ascii=False),
                    _to_pgvector(vec),
                )
            )

        deleted_total = 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                for doc_id, keep_ids in ids_by_doc.items():
                    cur.execute(
                        "DELETE FROM rag_chunks "
                        "WHERE strategy = %s AND document_id = %s AND NOT (chunk_id = ANY(%s));",
                        (strategy, doc_id, keep_ids),
                    )
                    deleted_total += max(0, cur.rowcount)

                cur.executemany(
                    """
                    INSERT INTO rag_chunks (
                        strategy, chunk_id, document_id, source, page,
                        section, year, category, text, metadata, embedding
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector)
                    ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                        document_id = EXCLUDED.document_id,
                        source = EXCLUDED.source,
                        page = EXCLUDED.page,
                        section = EXCLUDED.section,
                        year = EXCLUDED.year,
                        category = EXCLUDED.category,
                        text = EXCLUDED.text,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding;
                    """,
                    rows,
                )
            conn.commit()

        return {"deleted_obsolete": deleted_total, "upserted": len(rows)}

    def delete_document(self, strategy: str, document_id: str) -> int:
        """Remove all chunks belonging to a document for a strategy."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM rag_chunks WHERE strategy = %s AND document_id = %s;",
                    (strategy, document_id),
                )
                deleted = max(0, cur.rowcount)
            conn.commit()
        return deleted

    def search(
        self,
        strategy: str,
        query_vector: list[float],
        top_k: int = 3,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Filter permitted metadata in SQL and rank by exact cosine distance."""
        if len(query_vector) != self.dimensions:
            raise ValueError(
                f"Query vector dimension {len(query_vector)} != expected {self.dimensions}."
            )

        vec_literal = _to_pgvector(query_vector)
        where_clauses = ["strategy = %s"]
        filter_params: list[Any] = [strategy]

        if filters:
            for key, val in filters.items():
                col = ALLOWED_FILTER_COLUMNS.get(key)
                if col is None:
                    raise ValueError(f"Unsupported metadata filter key: {key!r}")
                where_clauses.append(f"{col} = %s")
                filter_params.append(val)

        sql = (
            "SELECT chunk_id, document_id, source, page, text, metadata, "
            "1.0 - (embedding <=> %s::vector) AS cosine_similarity "
            f"FROM rag_chunks WHERE {' AND '.join(where_clauses)} "
            "ORDER BY embedding <=> %s::vector ASC, chunk_id ASC "
            "LIMIT %s;"
        )
        params = [vec_literal, *filter_params, vec_literal, int(top_k)]

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            meta = row[5] if isinstance(row[5], dict) else json.loads(row[5])
            results.append(
                {
                    "chunk_id": row[0],
                    "document_id": row[1],
                    "source": row[2],
                    "page": int(row[3]),
                    "text": row[4],
                    "metadata": meta,
                    "score": round(float(row[6]), 6),
                }
            )
        return results
