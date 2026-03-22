"""
Semantic caching service.

Embeds workflow inputs using OpenAI text-embedding-3-small and compares them
against a rolling window of recent embeddings stored in Redis. If a new input
is semantically similar (cosine similarity ≥ threshold) to a previously
completed run, the cached output is returned immediately — skipping the entire
LLM pipeline.

This reduces cost and latency dramatically for repeated or near-duplicate
inputs (e.g. the same alert firing multiple times, similar customer complaints).

Architecture:
  - Embeddings are stored as JSON in Redis hashes under key `semcache:{run_id}`
  - A Redis list `semcache:index` maintains the rolling window of run_ids
  - Cosine similarity is computed in Python (no vector DB required)
  - All operations are O(N) where N ≤ semantic_cache_max_entries (default 500)

For production at scale, replace the in-Python similarity search with
Redis Stack's VSIM command or pgvector. The interface is identical.
"""

import json
import math
from dataclasses import dataclass

import redis.asyncio as aioredis

from app.config import settings
from app.services.logging_service import get_logger

logger = get_logger(__name__)

_INDEX_KEY = "semcache:index"
_ENTRY_PREFIX = "semcache:"

_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def reset_cache_client() -> None:
    """Clear the cached Redis client (required in Celery worker_process_init)."""
    global _redis_client
    _redis_client = None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity. Avoids numpy dependency."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _embed(text: str) -> list[float]:
    """Call OpenAI embeddings API. Returns a 1536-dim vector."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=text[:8000],  # text-embedding-3-small max context
    )
    return response.data[0].embedding


@dataclass
class CacheHit:
    run_id: str
    final_output: str
    similarity: float
    quality_score: float | None


async def check_cache(raw_input: str) -> CacheHit | None:
    """
    Look for a semantically similar previous run in Redis.

    Returns CacheHit if similarity ≥ threshold, None otherwise.
    Fails silently — cache misses are never errors.
    """
    if not settings.enable_semantic_cache:
        return None

    try:
        r = _get_redis()

        # Fetch the rolling index of recent run_ids
        run_ids: list[str] = await r.lrange(_INDEX_KEY, 0, settings.semantic_cache_max_entries - 1)
        if not run_ids:
            return None

        # Embed the query
        query_embedding = await _embed(raw_input)

        best_hit: CacheHit | None = None
        best_sim = settings.semantic_cache_threshold - 0.001  # must beat threshold

        for run_id in run_ids:
            entry_json = await r.get(f"{_ENTRY_PREFIX}{run_id}")
            if not entry_json:
                continue

            entry = json.loads(entry_json)
            embedding = entry.get("embedding")
            final_output = entry.get("final_output", "")

            if not embedding or not final_output:
                continue

            sim = _cosine_similarity(query_embedding, embedding)

            if sim > best_sim:
                best_sim = sim
                best_hit = CacheHit(
                    run_id=run_id,
                    final_output=final_output,
                    similarity=round(sim, 4),
                    quality_score=entry.get("quality_score"),
                )

        if best_hit:
            logger.info(
                "semantic_cache_hit",
                source_run_id=best_hit.run_id,
                similarity=best_hit.similarity,
            )

        return best_hit

    except Exception as e:
        logger.error("semantic_cache_check_failed", error=str(e))
        return None


async def store(run_id: str, raw_input: str, final_output: str, quality_score: float | None = None) -> None:
    """
    Embed and store a completed run's output in the semantic cache.

    Maintains the rolling window by trimming the index to max_entries.
    Fails silently — cache write failures must not affect run completion.
    """
    if not settings.enable_semantic_cache:
        return

    try:
        r = _get_redis()
        embedding = await _embed(raw_input)

        entry = {
            "embedding": embedding,
            "final_output": final_output,
            "quality_score": quality_score,
        }

        # Store the entry (TTL: 7 days)
        await r.set(
            f"{_ENTRY_PREFIX}{run_id}",
            json.dumps(entry),
            ex=7 * 24 * 3600,
        )

        # Push to rolling index and trim
        await r.lpush(_INDEX_KEY, run_id)
        await r.ltrim(_INDEX_KEY, 0, settings.semantic_cache_max_entries - 1)

        logger.debug("semantic_cache_stored", run_id=run_id)

    except Exception as e:
        logger.error("semantic_cache_store_failed", error=str(e))
