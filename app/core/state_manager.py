import json
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from app.utils.enums import RunStatus

_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def reset_redis_client() -> None:
    """Reset the cached Redis client. Call before asyncio.run() in Celery workers
    so each task gets a fresh client bound to the new event loop."""
    global _redis_client
    _redis_client = None


def _run_key(run_id: str) -> str:
    return f"run:{run_id}:status"


def _context_key(run_id: str) -> str:
    return f"run:{run_id}:context"


async def set_status(run_id: str, status: RunStatus) -> None:
    r = get_redis()
    await r.set(_run_key(run_id), status.value, ex=86400)  # 24h TTL


async def get_status(run_id: str) -> RunStatus | None:
    r = get_redis()
    value = await r.get(_run_key(run_id))
    if value is None:
        return None
    return RunStatus(value)


async def update_context(run_id: str, new_data: dict[str, Any]) -> None:
    r = get_redis()
    existing_raw = await r.get(_context_key(run_id))
    context: dict[str, Any] = json.loads(existing_raw) if existing_raw else {}
    context.update(new_data)
    await r.set(_context_key(run_id), json.dumps(context), ex=86400)


async def get_context(run_id: str) -> dict[str, Any]:
    r = get_redis()
    raw = await r.get(_context_key(run_id))
    return json.loads(raw) if raw else {}


async def append_completed_step(run_id: str, step_summary: dict[str, Any]) -> None:
    """Appends a step result to the accumulated context list for downstream steps."""
    context = await get_context(run_id)
    steps = context.get("completed_steps", [])
    steps.append(step_summary)
    await update_context(run_id, {"completed_steps": steps})


async def clear(run_id: str) -> None:
    r = get_redis()
    await r.delete(_run_key(run_id), _context_key(run_id))
