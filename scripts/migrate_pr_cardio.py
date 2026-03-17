"""
Migration script: Add cardio PR support to personal_records table.

Changes applied to the `personal_records` table:
  1. Make the `weight` column nullable (was NOT NULL).
  2. Make the `reps` column nullable (was NOT NULL).
  3. Add `calories` column (FLOAT, nullable) — stores the best calories burned for cardio PRs.
  4. Add `time_minutes` column (FLOAT, nullable) — stores the duration for the best cardio PR.

This script is safe to run on a live PostgreSQL database:
  - It only alters the `personal_records` table.
  - All other tables and their data are left untouched.
  - It is idempotent: columns that already exist are skipped.

Usage:
    DATABASE_URL=<your-db-url> python scripts/migrate_pr_cardio.py

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

if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
# Strip the psycopg3 driver suffix for the standard psycopg2-based migration
# connection, so that plain psycopg2 / pg8000 can be used without the app stack.
if database_url.startswith('postgresql+psycopg://'):
    database_url = database_url.replace('postgresql+psycopg://', 'postgresql://', 1)

engine = sa.create_engine(database_url)


def column_exists(conn, table_name: str, column_name: str) -> bool:
    """Return True if *column_name* already exists in *table_name*."""
    inspector = sa_inspect(conn)
    columns = [c['name'] for c in inspector.get_columns(table_name)]
    return column_name in columns


def column_is_nullable(conn, table_name: str, column_name: str) -> bool:
    """Return True if *column_name* in *table_name* is already nullable."""
    inspector = sa_inspect(conn)
    for col in inspector.get_columns(table_name):
        if col['name'] == column_name:
            return col.get('nullable', True)
    return True


def run_migration():
    with engine.begin() as conn:
        TABLE = 'personal_records'

        # ------------------------------------------------------------------
        # 1. Make `weight` nullable
        # ------------------------------------------------------------------
        if not column_is_nullable(conn, TABLE, 'weight'):
            print('  Altering column: weight -> nullable')
            conn.execute(text('ALTER TABLE personal_records ALTER COLUMN weight DROP NOT NULL'))
        else:
            print('  Skipping: weight is already nullable')

        # ------------------------------------------------------------------
        # 2. Make `reps` nullable
        # ------------------------------------------------------------------
        if not column_is_nullable(conn, TABLE, 'reps'):
            print('  Altering column: reps -> nullable')
            conn.execute(text('ALTER TABLE personal_records ALTER COLUMN reps DROP NOT NULL'))
        else:
            print('  Skipping: reps is already nullable')

        # ------------------------------------------------------------------
        # 3. Add `calories` column
        # ------------------------------------------------------------------
        if not column_exists(conn, TABLE, 'calories'):
            print('  Adding column: calories (FLOAT, nullable)')
            conn.execute(text('ALTER TABLE personal_records ADD COLUMN calories FLOAT'))
        else:
            print('  Skipping: calories column already exists')

        # ------------------------------------------------------------------
        # 4. Add `time_minutes` column
        # ------------------------------------------------------------------
        if not column_exists(conn, TABLE, 'time_minutes'):
            print('  Adding column: time_minutes (FLOAT, nullable)')
            conn.execute(text('ALTER TABLE personal_records ADD COLUMN time_minutes FLOAT'))
        else:
            print('  Skipping: time_minutes column already exists')

        print('Migration completed successfully.')


if __name__ == '__main__':
    print(f'Running cardio PR migration on: {engine.url.render_as_string(hide_password=True)}')
    run_migration()
