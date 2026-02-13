#!/usr/bin/env python3
"""
Migration script to add is_bodyweight column to exercises table.
Run this script to update existing databases with the new column.
"""

from app import app, db
from sqlalchemy import text

def migrate():
    with app.app_context():
        try:
            # Check if column already exists
            result = db.session.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='exercises' AND column_name='is_bodyweight'"
            ))
            
            if result.fetchone():
                print("Column 'is_bodyweight' already exists. No migration needed.")
                return
            
            # Add the new column with default value False
            db.session.execute(text(
                "ALTER TABLE exercises ADD COLUMN is_bodyweight BOOLEAN DEFAULT FALSE NOT NULL"
            ))
            db.session.commit()
            print("Successfully added 'is_bodyweight' column to exercises table.")
            
        except Exception as e:
            db.session.rollback()
            print(f"Error during migration: {e}")
            raise

if __name__ == '__main__':
    migrate()
