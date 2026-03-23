"""
AI Workflow Orchestrator
========================
Entry point for running the FastAPI application directly (outside Docker).

Usage:
    python main.py

For production, use the Docker Compose setup instead:
    docker-compose up --build
"""

import uvicorn

from app.config import settings
if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.app_env == "development",
        log_level=settings.log_level.lower(),
    )
