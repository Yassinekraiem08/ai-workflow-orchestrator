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


settings = Settings()
