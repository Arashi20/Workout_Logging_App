"""
Migration script: Allow multiple PR records per user+exercise (PR history).

Changes applied to the `personal_records` table:
  1. Drop the unique constraint `unique_user_exercise_pr` on (user_id, exercise_id)
     so that each new PR is stored as a separate row rather than overwriting the
     previous one.
  2. Create a plain (non-unique) index on (user_id, exercise_id) to keep
     look-ups fast (skipped if the index already exists).

After this migration the application will:
  - Insert a new row every time a personal record is beaten.
  - Keep all historical PR rows for data-analysis purposes.
  - Display only the most recent (best) PR per exercise on the PR page.
  - Export the full PR history in the CSV export.

This script is safe to run on a live PostgreSQL database:
  - It only alters the `personal_records` table.
  - All other tables and their data are left untouched.
  - It is idempotent: steps that have already been applied are skipped.

Usage:
    DATABASE_URL=<your-db-url> python scripts/migrate_pr_history.py

The DATABASE_URL can also be set in a .env file in the project root.
"""

import os
import sys
from pathlib import Path

# Allow importing project modules from the repo root.
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from dotenv import load_dotenv
load_dotenv(repo_root / '.env')

import sqlalchemy as sa
from sqlalchemy import text, inspect as sa_inspect

# ---------------------------------------------------------------------------
# Resolve and normalise the database URL
# ---------------------------------------------------------------------------
database_url = os.getenv('DATABASE_URL', '')
if not database_url:
    print('ERROR: DATABASE_URL environment variable is not set.')
    sys.exit(1)

# Normalize postgres:// to postgresql:// (Railway provides postgres://)
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

# Ensure we use psycopg (version 3) driver since that's what's installed
if database_url.startswith('postgresql://'):
    database_url = database_url.replace('postgresql://', 'postgresql+psycopg://', 1)

engine = sa.create_engine(database_url)


def constraint_exists(conn, table_name: str, constraint_name: str) -> bool:
    """Return True if a constraint with *constraint_name* exists on *table_name*."""
    inspector = sa_inspect(conn)
    unique_constraints = inspector.get_unique_constraints(table_name)
    return any(c['name'] == constraint_name for c in unique_constraints)


def index_exists(conn, table_name: str, index_name: str) -> bool:
    """Return True if an index with *index_name* exists on *table_name*."""
    inspector = sa_inspect(conn)
    indexes = inspector.get_indexes(table_name)
    return any(idx['name'] == index_name for idx in indexes)


def run_migration():
    with engine.begin() as conn:
        TABLE = 'personal_records'
        UNIQUE_CONSTRAINT = 'unique_user_exercise_pr'
        INDEX_NAME = 'ix_personal_records_user_exercise'

        # ------------------------------------------------------------------
        # 1. Drop the unique constraint (allows multiple rows per exercise)
        # ------------------------------------------------------------------
        if constraint_exists(conn, TABLE, UNIQUE_CONSTRAINT):
            print(f'  Dropping unique constraint: {UNIQUE_CONSTRAINT}')
            conn.execute(text(f'ALTER TABLE {TABLE} DROP CONSTRAINT {UNIQUE_CONSTRAINT}'))
        else:
            print(f'  Skipping: constraint {UNIQUE_CONSTRAINT!r} does not exist (already dropped)')

        # ------------------------------------------------------------------
        # 2. Add a plain index on (user_id, exercise_id) for query performance
        # ------------------------------------------------------------------
        if not index_exists(conn, TABLE, INDEX_NAME):
            print(f'  Creating index: {INDEX_NAME}')
            conn.execute(text(
                f'CREATE INDEX {INDEX_NAME} ON {TABLE} (user_id, exercise_id)'
            ))
        else:
            print(f'  Skipping: index {INDEX_NAME!r} already exists')

        print('Migration completed successfully.')


if __name__ == '__main__':
    print(f'Running PR history migration on: {engine.url.render_as_string(hide_password=True)}')
    run_migration()
