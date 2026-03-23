"""
Loads workflows.yml and exposes typed config objects to the rest of the application.

The config is cached after the first load.  Set the WORKFLOW_CONFIG_PATH env var
to point at a different file (useful in tests or multi-tenant deployments).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel


class ToolConfig(BaseModel):
    description: str
    args: str = ""


class RouteConfig(BaseModel):
    tools: list[str]


class InputTypeConfig(BaseModel):
    description: str
    default_route: str


class PlannerConfig(BaseModel):
    max_steps: int = 6
    min_steps: int = 2
    rules: list[str] = []


class WorkflowConfig(BaseModel):
    input_types: dict[str, InputTypeConfig]
    routes: dict[str, RouteConfig]
    tools: dict[str, ToolConfig]
    planner: PlannerConfig = PlannerConfig()


@lru_cache(maxsize=1)
def _load(config_path: str) -> WorkflowConfig:
    with open(config_path) as fh:
        raw = yaml.safe_load(fh)
    return WorkflowConfig(**raw)


def get_config() -> WorkflowConfig:
    config_path = os.environ.get(
        "WORKFLOW_CONFIG_PATH",
        str(Path(__file__).parent.parent.parent / "workflows.yml"),
    )
    return _load(config_path)
