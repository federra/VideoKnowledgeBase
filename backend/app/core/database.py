"""PostgreSQL connections. Callers own one explicit transaction per operation."""

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


def build_engine(url):
    parsed = make_url(url.get_secret_value() if hasattr(url, "get_secret_value") else url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL is required; SQLite cannot validate project constraints.")
    parsed = parsed.set(drivername="postgresql+psycopg")
    return create_engine(parsed, hide_parameters=True, pool_pre_ping=True)


@contextmanager
def transaction(engine):
    """Commit the whole operation or roll it back, including deferred constraints."""
    with engine.begin() as connection:
        yield connection


def application_engine():
    """Never fall back to the migration owner's credentials for business requests."""
    from app.core.config import settings

    if not settings.application_database_url:
        raise RuntimeError("APPLICATION_DATABASE_URL must use a restricted database login.")
    engine = build_engine(settings.application_database_url)
    try:
        with engine.connect() as c:
            unsafe = c.exec_driver_sql(
                "SELECT r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolbypassrls OR "
                "pg_has_role(current_user,t.tableowner,'MEMBER') "
                "FROM pg_roles r CROSS JOIN pg_tables t WHERE r.rolname=current_user "
                "AND t.schemaname='public' AND t.tablename='tasks'"
            ).scalar_one()
            if unsafe:
                raise RuntimeError(
                    "Business connections must not own tables or hold administrative roles."
                )
    except Exception:
        engine.dispose()
        raise
    return engine
