"""Gemini API embedding adapter with disk caching, RPM pacing, and zero mock fallback."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Protocol

from google import genai
from google.genai import errors as genai_errors
from google.genai import types


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        raise RuntimeError("Received zero-norm vector from embedding API.")
    return [float(x) / norm for x in vec]


def _extract_retry_seconds(message: str, attempt: int) -> float:
    m = re.search(r"retry in (\d+(?:\.\d+)?)(ms|s)", message, flags=re.IGNORECASE)
    if m:
        val = float(m.group(1))
        if m.group(2).lower() == "ms":
            val /= 1000.0
        if val >= 5.0:
            return val + 2.0
    return float(min(65, 20 * attempt))


class MyEmbedder:
    """Real Gemini API embedder using google-genai (never falls back to mock vectors)."""

    def __init__(
        self,
        model_name: str = "gemini-embedding-001",
        dimensions: int = 768,
        batch_size: int = 30,
        max_rpm: int = 90,
        cache_path: Path | None = None,
        api_key: str | None = None,
    ) -> None:
        resolved_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
        if not resolved_key:
            raise RuntimeError(
                "GEMINI_API_KEY is missing. Set it in starter/.env before running embeddings."
            )

        self.model_name = model_name.strip() or "gemini-embedding-001"
        self.dimensions = int(dimensions)
        self.batch_size = int(batch_size)
        self.max_rpm = int(max_rpm)
        self.client = genai.Client(api_key=resolved_key)
        self.cache_path = cache_path
        self._cache: dict[str, list[float]] = {}
        self._last_call_end: float | None = None
        self._last_batch_len: int = 0
        self.stats: dict[str, int | float] = {
            "api_calls": 0,
            "api_texts_embedded": 0,
            "cache_hits": 0,
            "total_chars_sent": 0,
            "api_seconds": 0.0,
            "rate_limit_waits": 0,
        }

        if self.cache_path and self.cache_path.exists():
            self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))

    def _cache_key(self, text: str, task_type: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{self.model_name}:{self.dimensions}:{task_type}:{digest}"

    def _save_cache(self) -> None:
        if self.cache_path is None:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._cache), encoding="utf-8")

    def _call_with_retry(
        self, batch_texts: list[str], task_type: str
    ) -> tuple[object, float]:
        max_attempts = 6
        for attempt in range(1, max_attempts + 1):
            t0 = time.perf_counter()
            try:
                response = self.client.models.embed_content(
                    model=self.model_name,
                    contents=batch_texts,
                    config=types.EmbedContentConfig(
                        task_type=task_type,
                        output_dimensionality=self.dimensions,
                    ),
                )
                return response, time.perf_counter() - t0
            except genai_errors.APIError as exc:
                msg = str(exc)
                is_rate_limit = getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in msg
                is_daily = "PerDay" in msg or "Daily" in msg
                if not is_rate_limit or is_daily or attempt == max_attempts:
                    raise
                wait_s = _extract_retry_seconds(msg, attempt)
                self.stats["rate_limit_waits"] = int(self.stats["rate_limit_waits"]) + 1
                print(
                    f"[MyEmbedder] Hit 429 per-minute quota (attempt {attempt}/{max_attempts}); "
                    f"waiting {wait_s:.1f}s...",
                    flush=True,
                )
                time.sleep(wait_s)
        raise RuntimeError("Unreachable retry loop exit in MyEmbedder.")

    def _embed_batch(self, texts: list[str], task_type: str) -> list[list[float]]:
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        missing_indices: list[int] = []
        missing_texts: list[str] = []

        for idx, text in enumerate(texts):
            key = self._cache_key(text, task_type)
            if key in self._cache:
                results[idx] = self._cache[key]
                self.stats["cache_hits"] += 1
            else:
                missing_indices.append(idx)
                missing_texts.append(text)

        total_missing = len(missing_texts)
        total_batches = (total_missing + self.batch_size - 1) // self.batch_size if total_missing else 0

        for b_idx, start in enumerate(range(0, total_missing, self.batch_size), start=1):
            if self.max_rpm > 0 and self._last_call_end is not None and self._last_batch_len > 0:
                min_interval = (self._last_batch_len * 60.0) / float(self.max_rpm)
                since_last = time.perf_counter() - self._last_call_end
                if since_last < min_interval:
                    time.sleep(min_interval - since_last)

            batch_texts = missing_texts[start : start + self.batch_size]
            batch_indices = missing_indices[start : start + self.batch_size]
            response, elapsed = self._call_with_retry(batch_texts, task_type)
            self._last_call_end = time.perf_counter()
            self._last_batch_len = len(batch_texts)

            embeddings = getattr(response, "embeddings", None) or []
            if len(embeddings) != len(batch_texts):
                raise RuntimeError(
                    f"Gemini API returned {len(embeddings)} vectors for {len(batch_texts)} inputs."
                )

            self.stats["api_calls"] += 1
            self.stats["api_texts_embedded"] += len(batch_texts)
            self.stats["total_chars_sent"] += sum(len(t) for t in batch_texts)
            self.stats["api_seconds"] = float(self.stats["api_seconds"]) + elapsed

            for pos, emb_obj in zip(batch_indices, embeddings):
                vec = _l2_normalize(list(emb_obj.values))
                if len(vec) != self.dimensions:
                    raise RuntimeError(
                        f"Expected vector dimension {self.dimensions}, got {len(vec)}."
                    )
                results[pos] = vec
                self._cache[self._cache_key(texts[pos], task_type)] = vec

            self._save_cache()
            print(
                f"[MyEmbedder:{task_type}] batch {b_idx}/{total_batches} "
                f"({min(start + len(batch_texts), total_missing)}/{total_missing} texts, {elapsed:.2f}s)",
                flush=True,
            )

        return [vec for vec in results if vec is not None]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed document chunks with Gemini RETRIEVAL_DOCUMENT task type."""
        return self._embed_batch(texts, task_type="RETRIEVAL_DOCUMENT")

    def embed_query(self, question: str) -> list[float]:
        """Embed a search query with Gemini RETRIEVAL_QUERY task type."""
        return self._embed_batch([question], task_type="RETRIEVAL_QUERY")[0]
