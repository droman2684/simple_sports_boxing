# db.py
import os
import psycopg
from psycopg.rows import dict_row

# Get DATABASE_URL from environment (Render and local .env)
DATABASE_URL = os.getenv("DATABASE_URL")

def get_conn():
    """
    Return a psycopg3 connection using dict_row so rows act like dicts.
    Usage:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
    """
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not found in environment.")
    
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def fetch_all(sql, params=None):
    """Return multiple rows."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.fetchall()

def fetch_one(sql, params=None):
    """Return a single row (or None)."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.fetchone()

def execute(sql, params=None):
    """Run INSERT/UPDATE/DELETE."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.rowcount

def executemany(sql, seq_of_params):
    """Run the same statement many times (batch)."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.executemany(sql, seq_of_params)
