"""
Postgres-backed storage for saved portfolios.

Local dev: points at the local Homebrew Postgres instance by default.
Deployed (Cloud Run): DATABASE_URL must be set to a *reachable* Postgres -
Cloud Run cannot reach a database running on someone's laptop. Which
reachable Postgres to use there (Cloud SQL, Neon, Supabase, ...) is a
separate decision, deliberately not made yet - this module doesn't care,
it just connects to whatever DATABASE_URL points at.

No ORM: one table, a handful of queries - plain SQL via psycopg is less
machinery than wiring up SQLAlchemy for this.
"""
import json
import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

# Local Homebrew Postgres default: trust-auth, current OS user as the role,
# running on port 5433 here (not the usual 5432 - it was already occupied).
DEFAULT_LOCAL_URL = "postgresql://tendani@localhost:5433/jse_portfolio"
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_LOCAL_URL)


class DatabaseUnavailable(RuntimeError):
    """Raised when the DB can't be reached - callers turn this into a 503,
    not a 500, since the rest of the app (optimize, universe) works fine
    without a database at all."""


@contextmanager
def get_connection():
    try:
        conn = psycopg.connect(DATABASE_URL, connect_timeout=5, row_factory=dict_row)
    except psycopg.OperationalError as e:
        raise DatabaseUnavailable(f"Could not reach the database: {e}") from e
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema():
    """Create the table if it doesn't exist yet. Called lazily on first use,
    not at import time - so the app still starts up fine (optimize/universe
    endpoints keep working) even if DATABASE_URL isn't reachable yet."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS saved_portfolios (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                kind TEXT NOT NULL,
                saved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                principal NUMERIC NOT NULL,
                expected_return DOUBLE PRECISION,
                expected_risk DOUBLE PRECISION,
                holdings JSONB NOT NULL
            )
        """)


_schema_ready = False


def _ensure_schema():
    global _schema_ready
    if not _schema_ready:
        init_schema()
        _schema_ready = True


def insert_saved_portfolio(kind: str, principal: float, holdings: list[dict],
                             expected_return: float | None, expected_risk: float | None) -> dict:
    _ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            """INSERT INTO saved_portfolios (kind, principal, expected_return, expected_risk, holdings)
               VALUES (%s, %s, %s, %s, %s)
               RETURNING id, kind, saved_at, principal, expected_return, expected_risk, holdings""",
            (kind, principal, expected_return, expected_risk, json.dumps(holdings)),
        ).fetchone()
        return row


def list_saved_portfolios() -> list[dict]:
    _ensure_schema()
    with get_connection() as conn:
        return conn.execute(
            """SELECT id, kind, saved_at, principal, expected_return, expected_risk, holdings
               FROM saved_portfolios ORDER BY saved_at DESC"""
        ).fetchall()


def delete_saved_portfolio(portfolio_id: str) -> bool:
    _ensure_schema()
    with get_connection() as conn:
        result = conn.execute("DELETE FROM saved_portfolios WHERE id = %s", (portfolio_id,))
        return result.rowcount > 0
