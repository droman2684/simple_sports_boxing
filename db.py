import os
import psycopg
from psycopg.rows import dict_row # This replaces DictCursor
from dotenv import load_dotenv

load_dotenv()

def get_conn():
    """
    Creates and returns a new database connection.
    Uses environment variables for connection info.
    """
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "boxing_software"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", ""),
        # This is the new way to get dictionary-like rows
        row_factory=dict_row 
    )

def fetch_all(sql, params=None):
    """
    Executes a SQL query and returns ALL results as a list of dicts.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

def fetch_one(sql, params=None):
    """
    Executes a SQL query and returns ONE result as a dict.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

def execute(sql, params=None):
    """
    Executes a SQL command (INSERT, UPDATE, DELETE) and commits the change.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        # The 'with get_conn()' block handles the commit automatically