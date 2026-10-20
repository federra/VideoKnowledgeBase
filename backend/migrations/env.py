"""Credentials are resolved at runtime and never copied into Alembic config/logs."""

import os

from alembic import context

from app.core.config import settings
from app.core.database import build_engine
from app.core.models import metadata

url = (
    os.environ.get("CIP_MIGRATION_URL") or settings.migration_database_url or settings.database_url
)
if not url:
    raise RuntimeError("A migration database URL must be configured privately.")
if context.is_offline_mode():
    raise RuntimeError(
        "Use online migrations: PostgreSQL integrity functions require the database."
    )
engine = build_engine(url)
with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=metadata,
        transactional_ddl=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
