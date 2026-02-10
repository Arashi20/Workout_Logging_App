"""
Migration script to add database indexes for performance optimization.
This script safely adds indexes to existing database tables without disrupting data.

Run this script once on your production database after deploying the updated models.py
Usage: python migrate_add_indexes.py
"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, Index, Table, MetaData, Column, Integer

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
    """Check if an index exists in PostgreSQL using parameterized query"""
    result = connection.execute(text("""
        SELECT 1 FROM pg_indexes 
        WHERE tablename = :table_name AND indexname = :index_name
    """), {"table_name": table_name, "index_name": index_name})
    return result.fetchone() is not None

def index_exists_sqlite(connection, metadata, table_name, index_name):
    """Check if an index exists in SQLite using SQLAlchemy inspector"""
    try:
        # Use SQLAlchemy's inspect to safely check for indexes
        from sqlalchemy import inspect
        inspector = inspect(connection)
        indexes = inspector.get_indexes(table_name)
        return any(idx['name'] == index_name for idx in indexes)
    except Exception:
        return False

def add_indexes():
    """Add indexes to improve query performance"""
    db_url = get_database_url()
    engine = create_engine(db_url)
    is_postgres = 'postgresql' in db_url
    metadata = MetaData()
    
    # Define single-column indexes to create: (table_name, column_name, index_name)
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
    
    # Define composite indexes to create: (table_name, [column_names], index_name)
    composite_indexes_to_create = [
        ('workout_sessions', ['user_id', 'end_time'], 'idx_user_active_session'),
        ('workout_logs', ['session_id', 'exercise_id'], 'idx_session_exercise'),
    ]
    
    try:
        if is_postgres:
            # For PostgreSQL, use AUTOCOMMIT for CONCURRENTLY option
            connection = engine.connect().execution_options(isolation_level='AUTOCOMMIT')
        else:
            connection = engine.connect()
        
        try:
            for table_name, column_name, index_name in indexes_to_create:
                # Check if index already exists
                try:
                    if is_postgres:
                        exists = index_exists_postgres(connection, table_name, index_name)
                    else:
                        exists = index_exists_sqlite(connection, metadata, table_name, index_name)
                    
                    if exists:
                        print(f"✓ Index {index_name} already exists on {table_name}.{column_name}")
                        continue
                except Exception as e:
                    print(f"⚠️  Could not check if index exists: {e}")
                
                # Create the index using SQLAlchemy DDL constructs for safety
                try:
                    # Reflect the table from the database with fresh metadata
                    table_metadata = MetaData()
                    table = Table(table_name, table_metadata, autoload_with=engine)
                    
                    # Create index using SQLAlchemy's Index construct
                    index = Index(index_name, table.c[column_name])
                    
                    if is_postgres:
                        # For PostgreSQL, use CREATE INDEX CONCURRENTLY
                        # This requires raw SQL as SQLAlchemy doesn't support CONCURRENTLY directly
                        create_stmt = str(index.create(bind=engine).compile(engine))
                        # Replace CREATE INDEX with CREATE INDEX CONCURRENTLY
                        create_stmt = create_stmt.replace('CREATE INDEX', 'CREATE INDEX CONCURRENTLY', 1)
                        connection.execute(text(create_stmt))
                    else:
                        # For SQLite, use standard CREATE INDEX IF NOT EXISTS
                        index.create(bind=connection, checkfirst=True)
                        connection.commit()
                    
                    print(f"✓ Created index {index_name} on {table_name}.{column_name}")
                except Exception as e:
                    error_msg = str(e).lower()
                    if 'already exists' in error_msg or 'duplicate' in error_msg:
                        print(f"✓ Index {index_name} already exists on {table_name}.{column_name}")
                    elif 'no such table' in error_msg or 'no such column' in error_msg:
                        print(f"⚠️  Table or column does not exist, skipping: {table_name}.{column_name}")
                    else:
                        print(f"✗ Error creating index {index_name}: {e}")
                    if not is_postgres:
                        connection.rollback()
            
            # Create composite indexes
            for table_name, column_names, index_name in composite_indexes_to_create:
                # Check if index already exists
                try:
                    if is_postgres:
                        exists = index_exists_postgres(connection, table_name, index_name)
                    else:
                        exists = index_exists_sqlite(connection, metadata, table_name, index_name)
                    
                    if exists:
                        print(f"✓ Composite index {index_name} already exists on {table_name}.({', '.join(column_names)})")
                        continue
                except Exception as e:
                    print(f"⚠️  Could not check if composite index exists: {e}")
                
                # Create the composite index
                try:
                    # Reflect the table from the database with fresh metadata
                    table_metadata = MetaData()
                    table = Table(table_name, table_metadata, autoload_with=engine)
                    
                    # Create composite index using SQLAlchemy's Index construct
                    columns = [table.c[col_name] for col_name in column_names]
                    index = Index(index_name, *columns)
                    
                    if is_postgres:
                        # For PostgreSQL, use CREATE INDEX CONCURRENTLY
                        create_stmt = str(index.create(bind=engine).compile(engine))
                        create_stmt = create_stmt.replace('CREATE INDEX', 'CREATE INDEX CONCURRENTLY', 1)
                        connection.execute(text(create_stmt))
                    else:
                        # For SQLite, use standard CREATE INDEX IF NOT EXISTS
                        index.create(bind=connection, checkfirst=True)
                        connection.commit()
                    
                    print(f"✓ Created composite index {index_name} on {table_name}.({', '.join(column_names)})")
                except Exception as e:
                    error_msg = str(e).lower()
                    if 'already exists' in error_msg or 'duplicate' in error_msg:
                        print(f"✓ Composite index {index_name} already exists on {table_name}.({', '.join(column_names)})")
                    elif 'no such table' in error_msg or 'no such column' in error_msg:
                        print(f"⚠️  Table or column does not exist, skipping: {table_name}.({', '.join(column_names)})")
                    else:
                        print(f"✗ Error creating composite index {index_name}: {e}")
                    if not is_postgres:
                        connection.rollback()
        finally:
            connection.close()
        
        engine.dispose()
        print("\n✅ Migration completed!")
        return 0
        
    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        return 1

if __name__ == '__main__':
    print("Starting database migration: Adding indexes for performance optimization\n")
    sys.exit(add_indexes())
