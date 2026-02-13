#!/usr/bin/env python3
"""
Migration script to add is_bodyweight column to exercises table.
Run this script to update existing databases with the new column.
"""

from app import app, db
from sqlalchemy import text, inspect

def migrate():
    with app.app_context():
        try:
            # Use SQLAlchemy inspector to check if column exists (works for both SQLite and PostgreSQL)
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('exercises')]
            
            if 'is_bodyweight' in columns:
                print("Column 'is_bodyweight' already exists. No migration needed.")
                return
            
            # Determine database type
            db_type = db.engine.dialect.name
            
            # Add the new column with default value False
            if db_type == 'sqlite':
                # SQLite uses 0/1 for boolean values instead of TRUE/FALSE
                db.session.execute(text(
                    "ALTER TABLE exercises ADD COLUMN is_bodyweight BOOLEAN DEFAULT 0 NOT NULL"
                ))
            else:
                # PostgreSQL and other databases
                db.session.execute(text(
                    "ALTER TABLE exercises ADD COLUMN is_bodyweight BOOLEAN DEFAULT FALSE NOT NULL"
                ))
            
            db.session.commit()
            print(f"Successfully added 'is_bodyweight' column to exercises table ({db_type}).")
            
        except Exception as e:
            db.session.rollback()
            print(f"Error during migration: {e}")
            raise

if __name__ == '__main__':
    migrate()
