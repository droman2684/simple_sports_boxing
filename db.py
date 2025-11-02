# db.py
import os
import psycopg2
import psycopg2.extras

# Prefer a single DATABASE_URL (works great with Neon)
DATABASE_URL = os.getenv("DATABASE_URL")

def get_conn():
    """
    Returns a new psycopg2 connection with DictCursor so rows act like dicts.
    """
    if DATABASE_URL:
        return psycopg2.connect(
            DATABASE_URL,
            cursor_factory=psycopg2.extras.DictCursor
        )
    # Fallback to individual env vars (useful for local dev)
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "boxing_software"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASS", ""),
        cursor_factory=psycopg2.extras.DictCursor
    )

def fetch_all(sql: str, params=None):
    """
    Run a SELECT that returns multiple rows.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.fetchall()

def fetch_one(sql: str, params=None):
    """
    Run a SELECT that returns a single row (or None).
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.fetchone()

def execute(sql: str, params=None):
    """
    Run an INSERT/UPDATE/DELETE (no rows returned).
    Returns number of rows affected.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.rowcount

def executemany(sql: str, seq_of_params):
    """
    Run the same statement against many parameter sets.
    """
    with get_conn() as conn, conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, seq_of_params)
        return cur.rowcount
