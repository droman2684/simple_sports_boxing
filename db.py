# db.py (CORRECTED)

import os
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

# THIS IS THE FIX:
# Look for the *variable* named "DATABASE_URL"
DATABASE_URL = os.getenv("DATABASE_URL")

def get_conn():
    """
    Creates and returns a new database connection.
    It uses the DATABASE_URL from the environment for production (on Render)
    or falls back to individual PG* vars for local development.
    """
    conn_string = DATABASE_URL
    
    # If DATABASE_URL is not set, build the string for local dev
    if not conn_string:
        conn_string = (
            f"host={os.getenv('PGHOST', 'localhost')} "
            f"port={os.getenv('PGPORT', '5432')} "
            f"dbname={os.getenv('PGDATABASE', 'boxing_software')} "
            f"user={os.getenv('PGUSER', 'postgres')} "
            f"password={os.getenv('PGPASSWORD')}" # Get local pw from .env
        )

    return psycopg.connect(conn_string, row_factory=dict_row)


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