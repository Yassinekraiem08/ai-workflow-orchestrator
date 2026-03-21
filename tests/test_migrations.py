"""
Migration tests — verify Alembic upgrade/downgrade without a live Postgres instance.
Uses SQLite in-memory via a synchronous connection override in alembic/env.py.
"""

from sqlalchemy import create_engine, inspect

from alembic import command
from alembic.config import Config


def test_migration_upgrade_and_downgrade():
    engine = create_engine("sqlite:///:memory:")

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", "sqlite:///:memory:")

    # Run upgrade to head
    with engine.connect() as conn:
        alembic_cfg.attributes["connection"] = conn
        command.upgrade(alembic_cfg, "head")

    tables = set(inspect(engine).get_table_names())
    assert {"workflow_runs", "workflow_steps", "tool_calls", "llm_traces"}.issubset(tables), (
        f"Expected all 4 tables after upgrade, got: {tables}"
    )

    # Run downgrade back to base (empty schema)
    with engine.connect() as conn:
        alembic_cfg.attributes["connection"] = conn
        command.downgrade(alembic_cfg, "base")

    tables_after = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert len(tables_after) == 0, (
        f"Expected empty schema after downgrade, got: {tables_after}"
    )
