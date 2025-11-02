# db.py
import os
import psycopg
from psycopg.rows import dict_row

# Get DB URL from environment (Render + local .env)
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set. Make sure it exists in Render env and/or .env file.")

def get_conn():
    """
    Create a connection with psycopg3 using dictionary rows.
    """
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def fetch_all(sql, params=None):
    """
    Fetch many rows from DB.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.fetchall()

def fetch_one(sql, params=None):
    """
    Fetch single row.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.fetchone()

def execute(sql, params=None):
    """
    Execute INSERT/UPDATE/DELETE.
    Returns number of affected rows.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.rowcount

def executemany(sql, param_list):
    """
    Execute many operations for batch inserts/updates.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.executemany(sql, param_list)
