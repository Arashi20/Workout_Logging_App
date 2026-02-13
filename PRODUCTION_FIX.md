# Production Database Schema Fix

## Problem
The app is showing an "Internal Server Error" because the database schema is out of sync with the code. Specifically, the `exercises` table is missing the `is_bodyweight` column.

## Solution

Since you're the sole user and currently just testing the app in production (no important data to preserve), the simplest solution is to reset the database tables.

### Steps to Fix:

1. **Access your Railway console** (or wherever your app is deployed)

2. **Run the reset command**:
   ```bash
   flask reset-db
   ```

   This will:
   - Drop all existing tables
   - Recreate all tables with the current schema (including the `is_bodyweight` column)
   - Automatically create your admin user using the credentials from your environment variables

3. **Verify the fix** by visiting:
   - `/exercises` - Should now work without errors
   - `/workout` - Should be accessible for logging workouts
   - `/prs` - Should display your personal records page

### What This Does

The `reset-db` command:
- ✅ Removes all tables (users, exercises, workout_sessions, workout_logs, personal_records, weight_logs, bloodwork_logs)
- ✅ Recreates them with the latest schema from `models.py`
- ✅ Automatically creates your admin user so you can log in immediately
- ⚠️ **Deletes all existing data** (which is fine since you're just testing)

### Future Schema Changes

Going forward, whenever you modify the database models in `models.py`:

**Option 1 - Quick Reset (recommended for testing)**:
```bash
flask reset-db
```

**Option 2 - Use Migration Scripts (if you want to preserve data)**:
```bash
python migrate_add_bodyweight.py  # or whichever migration you need
```

### Verification

After running `flask reset-db`, test these pages to confirm everything works:
- Login page: `https://your-app.railway.app/login`
- Exercises page: `https://your-app.railway.app/exercises`
- Workout logging: `https://your-app.railway.app/workout`
- PRs page: `https://your-app.railway.app/prs`

All should now work without internal server errors!
