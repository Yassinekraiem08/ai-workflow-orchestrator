from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # OpenAI
    openai_api_key: str = ""
    llm_model: str = "gpt-4o"

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/workflow_db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    # Orchestrator
    max_tool_retries: int = 3
    max_celery_retries: int = 3
    step_timeout_seconds: int = 60
    celery_retry_delay_seconds: int = 30
    max_replan_depth: int = 2  # max times re-planner can inject new steps per run

    # Auth
    api_keys: str = "dev-key-changeme"  # comma-separated list; set via API_KEYS env var
    jwt_secret: str = "changeme-in-production"  # override in prod via JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # LLM model routing
    llm_model_fast: str = "gpt-4o-mini"   # classifier, planner, replanner, fallback
    llm_model_strong: str = "gpt-4o"      # executor agent

    # Human-in-the-loop threshold
    confidence_threshold: float = 0.65    # classifier confidence below this → needs_review

    # Observability
    otel_enabled: bool = False
    otlp_endpoint: str = ""  # e.g. http://jaeger:4318/v1/traces

    # Safety layer
    enable_safety_check: bool = True

    # LLM-as-judge
    enable_judge: bool = True
    judge_model: str = "gpt-4o-mini"  # cheap + fast; upgrade to gpt-4o for higher fidelity

    # Semantic cache
    enable_semantic_cache: bool = True
    semantic_cache_threshold: float = 0.92   # cosine similarity required for a cache hit
    semantic_cache_max_entries: int = 500     # rolling window of embeddings kept in Redis
    embedding_model: str = "text-embedding-3-small"  # 1536-dim, ~$0.00002/1K tokens


settings = Settings()
