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


settings = Settings()
