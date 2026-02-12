#!/usr/bin/env python3
"""
Database migration: Add full_name column to dashboard_members table

Run this ONCE after deploying the updated code.
"""

from database import engine
from sqlalchemy import text

def migrate():
    """Add full_name column to dashboard_members"""
    with engine.connect() as conn:
        # Add column if it doesn't exist
        conn.execute(text("""
            ALTER TABLE dashboard_members 
            ADD COLUMN IF NOT EXISTS full_name VARCHAR(255);
        """))
        
        # Backfill existing records (use username as full_name temporarily)
        conn.execute(text("""
            UPDATE dashboard_members 
            SET full_name = username 
            WHERE full_name IS NULL;
        """))
        
        conn.commit()
    
    print("✅ Migration complete: full_name column added to dashboard_members")

if __name__ == "__main__":
    migrate()
