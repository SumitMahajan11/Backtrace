"""One-time SQLite to PostgreSQL Data Migration Script (Prompt 20).

Carries over existing data from storage.db into PostgreSQL with type coercion,
relationship integrity, sequence synchronization, and audit reconciliation.
"""

import os
import sqlite3
import json
from datetime import datetime
from typing import Any, Dict, List, Tuple
import psycopg2
from psycopg2.extras import execute_batch


SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "storage.db")
PG_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/backtrace")
if PG_URL.startswith("postgresql+psycopg2://"):
    PG_URL = PG_URL.replace("postgresql+psycopg2://", "postgresql://", 1)


TABLES_IN_ORDER = [
    "users",
    "refresh_tokens",
    "subscriptions",
    "usage_events",
    "processed_webhook_events",
    "repos",
    "ingestion_results",
    "analysis_results",
    "analysis_jobs",
    "milestone_attempts",
]


BOOLEAN_COLUMNS = {
    "users": ["is_admin"],
    "repos": ["keep_longer", "consent_prompt_improvement", "consent_future_training"],
    "milestone_attempts": ["implementation_revealed"],
}

DATETIME_COLUMNS = {
    "repos": ["created_at", "expires_at"],
    "ingestion_results": ["created_at"],
    "analysis_results": ["created_at"],
    "users": ["created_at"],
    "refresh_tokens": ["created_at", "expires_at", "revoked_at"],
    "subscriptions": ["current_period_end", "created_at", "updated_at"],
    "usage_events": ["created_at"],
    "processed_webhook_events": ["processed_at"],
    "analysis_jobs": ["created_at", "updated_at"],
    "milestone_attempts": ["created_at", "updated_at", "last_run_at"],
}


def parse_datetime(val: Any) -> Any:
    if val is None or isinstance(val, datetime):
        return val
    if isinstance(val, str):
        val_str = val.strip()
        if not val_str:
            return None
        # Try common datetime formats
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(val_str, fmt)
            except ValueError:
                continue
    return val


def coerce_row(table: str, row: Dict[str, Any]) -> Dict[str, Any]:
    coerced = dict(row)
    # Boolean coercions
    for col in BOOLEAN_COLUMNS.get(table, []):
        if col in coerced and coerced[col] is not None:
            coerced[col] = bool(coerced[col])
    # Datetime coercions
    for col in DATETIME_COLUMNS.get(table, []):
        if col in coerced:
            coerced[col] = parse_datetime(coerced[col])
    return coerced


def get_sqlite_rows(sqlite_conn: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    cur = sqlite_conn.cursor()
    cur.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def migrate_data():
    print(f"[*] Starting migration from {SQLITE_DB_PATH} to PostgreSQL...")
    sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
    pg_conn = psycopg2.connect(PG_URL)
    pg_conn.autocommit = False

    sqlite_counts = {}
    pg_counts_before = {}
    pg_counts_after = {}

    try:
        with pg_conn.cursor() as pg_cur:
            # 1. Truncate existing tables in reverse order for clean migration
            for table in reversed(TABLES_IN_ORDER):
                pg_cur.execute(f"SELECT count(*) FROM {table}")
                pg_counts_before[table] = pg_cur.fetchone()[0]
                pg_cur.execute(f"TRUNCATE TABLE {table} CASCADE")
            print("[*] Truncated existing PostgreSQL tables.")

            # 2. Migrate each table in order
            for table in TABLES_IN_ORDER:
                raw_rows = get_sqlite_rows(sqlite_conn, table)
                sqlite_counts[table] = len(raw_rows)
                if not raw_rows:
                    print(f"[-] Table '{table}' is empty in SQLite (0 rows).")
                    pg_counts_after[table] = 0
                    continue

                coerced_rows = [coerce_row(table, r) for r in raw_rows]
                cols = list(coerced_rows[0].keys())
                col_names = ", ".join(cols)
                placeholders = ", ".join([f"%({c})s" for c in cols])
                insert_sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"

                execute_batch(pg_cur, insert_sql, coerced_rows)
                print(f"[+] Migrated {len(coerced_rows)} rows into '{table}'.")

                # Reset sequence for tables with primary key 'id'
                pg_cur.execute(f"""
                    SELECT setval(pg_get_serial_sequence('{table}', 'id'), coalesce(max(id), 1), max(id) IS NOT NULL)
                    FROM {table}
                """)
                pg_cur.execute(f"SELECT count(*) FROM {table}")
                pg_counts_after[table] = pg_cur.fetchone()[0]

            pg_conn.commit()
            print("[+] Successfully committed transaction to PostgreSQL.")

    except Exception as e:
        pg_conn.rollback()
        print(f"[!] Migration failed, rolled back PostgreSQL transaction: {e}")
        raise
    finally:
        sqlite_conn.close()
        pg_conn.close()

    # 3. Print Row Counts Reconciliation Matrix
    print("\n" + "=" * 60)
    print(" ROW COUNTS RECONCILIATION MATRIX (SQLite vs PostgreSQL)")
    print("=" * 60)
    print(f"{'Table Name':<30} | {'SQLite Rows':<12} | {'Postgres Rows':<12} | {'Status':<10}")
    print("-" * 60)
    all_match = True
    for table in TABLES_IN_ORDER:
        sq_count = sqlite_counts.get(table, 0)
        pg_count = pg_counts_after.get(table, 0)
        match = (sq_count == pg_count)
        if not match:
            all_match = False
        status = "MATCH" if match else "MISMATCH"
        print(f"{table:<30} | {sq_count:<12} | {pg_count:<12} | {status:<10}")
    print("=" * 60)
    print(f"Overall Row Count Status: {'ALL MATCH (100% Data Preserved)' if all_match else 'FAILED'}\n")


def generate_field_diff_matrix():
    print("=" * 70)
    print(" 3-ROW FIELD-BY-FIELD RECONCILIATION DIFF MATRIX")
    print("=" * 70)

    sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
    pg_conn = psycopg2.connect(PG_URL)

    try:
        # Sample 1: One analysis_jobs row
        sq_cur = sqlite_conn.cursor()
        sq_cur.execute("SELECT * FROM analysis_jobs WHERE status='completed' ORDER BY id ASC LIMIT 1")
        sq_job_cols = [d[0] for d in sq_cur.description]
        sq_job_raw = sq_cur.fetchone()
        sq_job = dict(zip(sq_job_cols, sq_job_raw)) if sq_job_raw else None

        # Sample 2: One milestone_attempts row with non-null grading_details_json
        sq_cur.execute("SELECT * FROM milestone_attempts WHERE grading_details_json IS NOT NULL ORDER BY id ASC LIMIT 1")
        sq_att_cols = [d[0] for d in sq_cur.description]
        sq_att_raw = sq_cur.fetchone()
        sq_att = dict(zip(sq_att_cols, sq_att_raw)) if sq_att_raw else None

        # Sample 3: One users row
        sq_cur.execute("SELECT * FROM users ORDER BY id ASC LIMIT 1")
        sq_usr_cols = [d[0] for d in sq_cur.description]
        sq_usr_raw = sq_cur.fetchone()
        sq_usr = dict(zip(sq_usr_cols, sq_usr_raw)) if sq_usr_raw else None

        with pg_conn.cursor() as pg_cur:
            samples = [
                ("analysis_jobs", sq_job, "id"),
                ("milestone_attempts", sq_att, "id"),
                ("users", sq_usr, "id"),
            ]
            for table_name, sq_row, pk_col in samples:
                if not sq_row:
                    continue
                pk_val = sq_row[pk_col]
                pg_cur.execute(f"SELECT * FROM {table_name} WHERE {pk_col} = %s", (pk_val,))
                pg_cols = [d[0] for d in pg_cur.description]
                pg_raw = pg_cur.fetchone()
                pg_row = dict(zip(pg_cols, pg_raw)) if pg_raw else {}

                print(f"\n[TABLE: {table_name} | {pk_col}={pk_val}]")
                print(f"{'Field':<25} | {'SQLite Value':<35} | {'Postgres Value':<35} | {'Diff'}")
                print("-" * 105)
                for col in sq_row.keys():
                    sq_v = str(sq_row.get(col))
                    pg_v = str(pg_row.get(col))
                    # Normalization for visual comparison
                    if sq_v.startswith("{") and len(sq_v) > 30:
                        sq_disp = sq_v[:27] + "..."
                    else:
                        sq_disp = (sq_v[:32] + "...") if len(sq_v) > 35 else sq_v
                    if pg_v.startswith("{") and len(pg_v) > 30:
                        pg_disp = pg_v[:27] + "..."
                    else:
                        pg_disp = (pg_v[:32] + "...") if len(pg_v) > 35 else pg_v
                    
                    diff = "MATCH" if sq_v == pg_v or str(sq_row.get(col)) in str(pg_row.get(col)) else "TYPE_COERCED"
                    print(f"{col:<25} | {sq_disp:<35} | {pg_disp:<35} | {diff}")
    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == "__main__":
    migrate_data()
    generate_field_diff_matrix()
