import os
import psycopg
from psycopg.rows import dict_row  # This replaces DictCursor
from dotenv import load_dotenv

load_dotenv()

# Get the database URL from the environment.
# Render provides this automatically.
DATABASE_URL = os.getenv("postgresql://neondb_owner:npg_is8yVxob3vUp@ep-wild-dust-ah7i6fep-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require")

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
            f"password={os.getenv('PGPASSWORD', 'Aviators2025!!')}"
        )

    return psycopg.connect(conn_string, row_factory=dict_row)

# --- No changes needed to the functions below ---

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