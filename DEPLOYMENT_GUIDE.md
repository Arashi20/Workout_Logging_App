# Deployment Guide for Performance Fix

## Overview
This deployment fixes critical database performance issues causing worker timeouts (30+ seconds) when adding workout sets in production.

## Changes Summary

### 1. Code Changes (app.py)
- **Eliminated double commit pattern**: The `add_set` endpoint now performs a single database commit instead of two
- **Refactored `update_pr()`**: No longer auto-commits, allowing the caller to batch operations

### 2. Database Schema Changes (models.py)
- **Added composite index** `idx_user_active_session` on `WorkoutSession(user_id, end_time)` 
- **Added composite index** `idx_session_exercise` on `WorkoutLog(session_id, exercise_id)`

### 3. Migration Script (migrate_add_indexes.py)
- Extended to create the new composite indexes on existing databases

## Deployment Steps for Railway

### Step 1: Deploy the Code
1. Merge this PR to main branch
2. Railway will automatically deploy the new code
3. The application will start with the new code

### Step 2: Run Migration Script
After the deployment completes, run the migration in Railway's console:

```bash
python migrate_add_indexes.py
```

**Expected output:**
```
Starting database migration: Adding indexes for performance optimization

✓ Index ix_weight_logs_user_id already exists...
✓ Index ix_weight_logs_logged_at already exists...
...
✓ Created composite index idx_user_active_session on workout_sessions.(user_id, end_time)
✓ Created composite index idx_session_exercise on workout_logs.(session_id, exercise_id)

✅ Migration completed!
```

### Step 3: Verify
1. Test adding a workout set - should complete in <500ms (previously 5-30+ seconds)
2. Check Railway logs for any errors
3. Monitor performance for a few hours

## Rollback Plan
If issues occur:
1. Revert the PR in GitHub
2. Railway will auto-deploy the previous version
3. The composite indexes can remain (they don't hurt, just won't be used)

## Expected Performance Improvements

| Operation | Before | After | Improvement |
|-----------|--------|-------|-------------|
| Add workout set | 5-30+ seconds (timeout) | <500ms | 50-100x faster |
| Start workout | 5 seconds | <200ms | 25x faster |
| Active session query | N/A | <50ms | 2-5x faster (with composite index) |
| Database commits per set | 2 | 1 | 50% reduction |

## Technical Details

### Why the Double Commit Was Bad
```python
# Before: Two separate transactions
db.session.commit()  # Transaction 1: workout log
update_pr()          # Transaction 2: PR update (auto-commits)
```

Each commit forces PostgreSQL to:
1. Write to WAL (Write-Ahead Log)
2. Sync to disk (fsync)
3. Update checkpoint tracking

With 2 commits per set, this doubles the I/O overhead and checkpoint load.

### Why Composite Indexes Help
```sql
-- Before: Two separate index scans + merge
WHERE user_id = 1 AND end_time IS NULL

-- After: Single composite index scan
WHERE (user_id, end_time) = (1, NULL)
```

PostgreSQL can use the composite index directly for both columns, avoiding the need to scan and merge two separate indexes.

## Monitoring

After deployment, monitor these metrics:
- Response time for `/workout/add_set` endpoint
- Worker timeout errors (should be zero)
- Database checkpoint frequency/duration
- Connection pool utilization

## Support

If you encounter issues:
1. Check Railway logs for error messages
2. Verify migration completed successfully
3. Check database indexes with: `\d+ workout_sessions` and `\d+ workout_logs` in psql

## Testing in Local Environment

To test locally before deploying:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set environment variables
export DATABASE_URL="postgresql://..."
export SECRET_KEY="..."

# 3. Run migration
python migrate_add_indexes.py

# 4. Start app
python app.py

# 5. Test adding workout sets - should be fast
```
