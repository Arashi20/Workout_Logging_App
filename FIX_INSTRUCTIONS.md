# URGENT FIX: Missing is_bodyweight Column Error

## Problem
Your Railway PostgreSQL database is missing the `is_bodyweight` column in the `exercises` table, causing this error:
```
psycopg.errors.UndefinedColumn: column exercises.is_bodyweight does not exist
```

## Solution (1 Command)

**Open your Railway console and run:**
```bash
flask migrate-schema
```

That's it! This single command will:
- ✅ Detect the missing column
- ✅ Add it to your database
- ✅ Keep all your existing data
- ✅ Set the default value (False) for existing exercises

## Expected Output
```
Running schema migrations...
Current columns in exercises table: id, name, description, exercise_type, created_at
Adding is_bodyweight column to exercises table...
✓ Successfully added is_bodyweight column (postgresql).

All migrations completed successfully!
```

## After Running the Command
1. The error should be gone
2. The exercises page should work normally
3. All your existing exercises are preserved
4. You can safely run this command again if needed (it won't duplicate the column)

## How to Run in Railway
1. Go to your Railway project
2. Click on your service
3. Click "Console" or "Shell" tab
4. Type: `flask migrate-schema`
5. Press Enter
6. Wait for the success message
7. Restart your service (Railway should do this automatically)

## Alternative: If Command Not Found
If `flask` command is not found, try:
```bash
python -m flask migrate-schema
```

## Why Did This Happen?
- The previous database reset commands (`flask reset-db` or manual deletions) don't work properly in production
- `db.create_all()` only creates NEW tables, it doesn't add columns to EXISTING tables
- That's why we created this new `migrate-schema` command that uses `ALTER TABLE` SQL statements

## Important Notes
- ✅ This is safe - it only ADDS the column, doesn't delete anything
- ✅ Safe to run multiple times - if column exists, it skips it
- ✅ Works with PostgreSQL (and SQLite for local development)
- ✅ No data loss - all your existing exercises remain intact

## If You Have Any Issues
See the full [DATABASE_MIGRATION_GUIDE.md](DATABASE_MIGRATION_GUIDE.md) for:
- Detailed troubleshooting steps
- Manual SQL commands (if needed)
- Common issues and solutions
- How to verify the fix worked

## Quick Verification
After running the migration, check that the exercises page loads without errors. You should see all your exercises listed normally.
