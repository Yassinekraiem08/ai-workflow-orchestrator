import uuid
from datetime import UTC, datetime


def generate_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def generate_step_id() -> str:
    return f"step_{uuid.uuid4().hex[:12]}"


def generate_trace_id() -> str:
    return f"trace_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


def truncate_for_log(text: str, max_length: int = 200) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length] + f"... [{len(text) - max_length} chars truncated]"


def ms_since(start: datetime) -> int:
    delta = utcnow() - start
    return int(delta.total_seconds() * 1000)
