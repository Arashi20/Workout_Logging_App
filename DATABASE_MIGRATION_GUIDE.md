# Database Migration Guide

This guide helps you update your database schema when new columns or features are added to the app.

## Quick Fix for Missing `is_bodyweight` Column Error

If you're seeing an error like:
```
psycopg.errors.UndefinedColumn: column exercises.is_bodyweight does not exist
```

### Solution: Run the Migration Command

**In Railway Console** (or your deployment environment):

```bash
flask migrate-schema
```

This command will:
- ✅ Check your current database schema
- ✅ Add any missing columns (like `is_bodyweight`)
- ✅ Preserve all your existing data
- ✅ Display what changes were made

### Expected Output

```
Running schema migrations...
Current columns in exercises table: id, name, description, exercise_type, created_at
Adding is_bodyweight column to exercises table...
✓ Successfully added is_bodyweight column (postgresql).

All migrations completed successfully!
```

### Verification

After running the migration, try accessing the exercises page again. The error should be resolved and your existing exercises should all be displayed.

## Why This Happens

When you update your app code to a new version that includes schema changes:
- The Python models (in `models.py`) define the new schema
- But your existing database still has the old schema
- You need to run a migration to update the database structure

## Alternative Methods

### Method 1: Using the New Migration Command (Recommended)
```bash
flask migrate-schema
```
**Pros:**
- ✅ Simple one command
- ✅ Preserves all data
- ✅ Safe to run multiple times
- ✅ Works for both SQLite and PostgreSQL

### Method 2: Manual SQL (Advanced Users)
If the migration command doesn't work, you can manually add the column:

**For PostgreSQL:**
```sql
ALTER TABLE exercises ADD COLUMN is_bodyweight BOOLEAN DEFAULT FALSE NOT NULL;
```

**For SQLite:**
```sql
ALTER TABLE exercises ADD COLUMN is_bodyweight BOOLEAN DEFAULT 0 NOT NULL;
```

### Method 3: Full Reset (Development Only - DELETES ALL DATA)
⚠️ **WARNING:** This will delete all your data! Only use for testing.

```bash
flask reset-db
```

## Troubleshooting

### Issue: "Column already exists" but still getting errors

**Possible causes:**
1. The migration was partially applied
2. Database connection issues
3. Cached connections

**Solution:**
1. Restart your application/server
2. Run the migration again: `flask migrate-schema`
3. Check your database connection settings

### Issue: Permission denied when running migration

**Solution:**
Ensure your database user has `ALTER TABLE` permissions. In Railway, the default PostgreSQL user should have these permissions.

### Issue: Migration command not found

**Solution:**
1. Ensure you're in the correct directory
2. Verify Flask is installed: `pip list | grep Flask`
3. Try: `python -m flask migrate-schema`

## Best Practices

1. **Always backup your database** before running migrations in production
   
   **For Railway PostgreSQL:**
   - Railway doesn't have built-in backup UI, but you can use `pg_dump`:
   ```bash
   # In Railway console or locally with DATABASE_URL
   pg_dump $DATABASE_URL > backup_$(date +%Y%m%d).sql
   ```
   - Alternatively, Railway automatically creates daily backups (check your plan)
   - For critical data, consider using Railway's built-in backup features or external backup solutions
   
   **For SQLite (local development):**
   ```bash
   cp workout.db workout.db.backup
   ```

2. **Test migrations locally first** if possible
3. **Run migrations during low-traffic periods** to minimize user impact
4. **Monitor logs** after migration to ensure everything works correctly

## Getting Help

If you continue to have issues:
1. Check the Railway logs for detailed error messages
2. Verify your DATABASE_URL is correctly set
3. Ensure you have the latest version of the code deployed
4. Try restarting your Railway service after the migration

## Future Schema Changes

Whenever you pull updates that include model changes:
1. Check the README for any migration notes
2. Run `flask migrate-schema` to apply the changes
3. Restart your application if needed

The `migrate-schema` command is designed to be safe and idempotent - you can run it multiple times without issues.
