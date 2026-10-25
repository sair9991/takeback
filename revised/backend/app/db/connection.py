from contextlib import contextmanager
from typing import Any, Generator, Optional
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from app.config import settings

_pool: Optional[ConnectionPool] = None


def get_pool() -> ConnectionPool:
    """Return the global connection pool, initializing it if closed."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.DATABASE_URL,
            min_size=2,
            max_size=20,
            timeout=30.0,
            kwargs={"row_factory": dict_row},
        )
    return _pool


def close_pool() -> None:
    """Close all active pooled connections."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    """Yield a connection checked out from the pool."""
    pool = get_pool()
    with pool.connection() as conn:
        yield conn


def query(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Execute select query and return list of dict rows."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]


def query_one(sql: str, params: tuple[Any, ...] = ()) -> Optional[dict[str, Any]]:
    """Execute select query and return first row or None."""
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple[Any, ...] = ()) -> int:
    """Execute insert, update, or delete query and commit transaction."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
            return cur.rowcount
