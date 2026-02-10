"""
Migration script to add database indexes for performance optimization.
This script safely adds indexes to existing database tables without disrupting data.

Run this script once on your production database after deploying the updated models.py
Usage: python migrate_add_indexes.py
"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

def get_database_url():
    """Get and normalize the database URL"""
    db_url = os.getenv('DATABASE_URL', 'sqlite:///workout.db')
    
    # Normalize to use psycopg driver
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql+psycopg://')
    elif db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', 'postgresql+psycopg://')
    
    return db_url

def index_exists_postgres(connection, table_name, index_name):
    """Check if an index exists in PostgreSQL"""
    result = connection.execute(text("""
        SELECT 1 FROM pg_indexes 
        WHERE tablename = :table_name AND indexname = :index_name
    """), {"table_name": table_name, "index_name": index_name})
    return result.fetchone() is not None

def index_exists_sqlite(connection, table_name, index_name):
    """Check if an index exists in SQLite"""
    result = connection.execute(text(f"PRAGMA index_list('{table_name}')"))
    indexes = result.fetchall()
    return any(idx[1] == index_name for idx in indexes)

def add_indexes():
    """Add indexes to improve query performance"""
    db_url = get_database_url()
    engine = create_engine(db_url)
    is_postgres = 'postgresql' in db_url
    
    # Define indexes to create: (table_name, column_name, index_name)
    indexes_to_create = [
        ('weight_logs', 'user_id', 'ix_weight_logs_user_id'),
        ('weight_logs', 'logged_at', 'ix_weight_logs_logged_at'),
        ('workout_sessions', 'user_id', 'ix_workout_sessions_user_id'),
        ('workout_sessions', 'end_time', 'ix_workout_sessions_end_time'),
        ('workout_logs', 'session_id', 'ix_workout_logs_session_id'),
        ('workout_logs', 'exercise_id', 'ix_workout_logs_exercise_id'),
        ('personal_records', 'user_id', 'ix_personal_records_user_id'),
        ('personal_records', 'exercise_id', 'ix_personal_records_exercise_id'),
        ('bloodwork_logs', 'user_id', 'ix_bloodwork_logs_user_id'),
        ('bloodwork_logs', 'test_date', 'ix_bloodwork_logs_test_date'),
    ]
    
    try:
        with engine.connect() as connection:
            for table_name, column_name, index_name in indexes_to_create:
                # Check if index already exists
                try:
                    if is_postgres:
                        exists = index_exists_postgres(connection, table_name, index_name)
                    else:
                        exists = index_exists_sqlite(connection, table_name, index_name)
                    
                    if exists:
                        print(f"✓ Index {index_name} already exists on {table_name}.{column_name}")
                        continue
                except Exception as e:
                    print(f"⚠️  Could not check if index exists: {e}")
                
                # Create the index
                try:
                    if is_postgres:
                        sql = text(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name} ON {table_name} ({column_name})")
                    else:
                        sql = text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_name})")
                    
                    connection.execute(sql)
                    connection.commit()
                    print(f"✓ Created index {index_name} on {table_name}.{column_name}")
                except Exception as e:
                    error_msg = str(e).lower()
                    if 'already exists' in error_msg or 'duplicate' in error_msg:
                        print(f"✓ Index {index_name} already exists on {table_name}.{column_name}")
                    else:
                        print(f"✗ Error creating index {index_name}: {e}")
                    connection.rollback()
        
        engine.dispose()
        print("\n✅ Migration completed!")
        return 0
        
    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        return 1

if __name__ == '__main__':
    print("Starting database migration: Adding indexes for performance optimization\n")
    sys.exit(add_indexes())
