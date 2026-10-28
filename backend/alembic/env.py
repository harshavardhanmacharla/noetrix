"""
Alembic environment configuration.
Reads DATABASE_URL from the application settings so migrations use the same DB as the app.
"""
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Make sure the app package is importable when running alembic from the
# backend/ directory.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.database import Base  # noqa: E402 — import after sys.path fix

# Import all models so Alembic's autogenerate can discover them
import app.models.organization  # noqa: F401
import app.models.user  # noqa: F401
import app.models.project  # noqa: F401
import app.models.test_case  # noqa: F401
import app.models.test_run  # noqa: F401
import app.models.discovery  # noqa: F401

# ---------------------------------------------------------------------------
# Alembic Config object
# ---------------------------------------------------------------------------
config = context.config

# Set the sqlalchemy.url from our application settings so the alembic.ini
# placeholder is never used in production.
settings = get_settings()
existing_url = config.get_main_option("sqlalchemy.url")
if not existing_url or "driver://user:pass" in existing_url:
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generate SQL without a live DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — execute against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
