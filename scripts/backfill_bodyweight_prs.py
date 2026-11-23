"""
Backfill: NULL weight on bodyweight sets, and the PRs those sets missed.

Background
----------
Plain bodyweight sets (no extra load) were saved with weight = NULL when the
"Extra Weight (kg)" field was left blank, and weight = 0.0 when "0" was typed.
finish_workout() only checked PRs for sets with a non-NULL weight, so NULL-weight
bodyweight sets never reached update_pr() and could not set a PR
(e.g. Push-Up 28 reps on 2026-11-23, session 270).

What this script does
---------------------
1. Backs up `workout_logs` and `personal_records` to a timestamped JSON file
   (only when --apply is given, before anything is written).
2. Runs, inside one transaction:

       UPDATE workout_logs
       SET weight = 0.0
       WHERE weight IS NULL
         AND reps IS NOT NULL
         AND exercise_id IN (
             SELECT id FROM exercises
             WHERE is_bodyweight = TRUE AND is_cardio = FALSE
         );

3. Replays PR detection (same rule as update_pr: higher weight wins, equal
   weight + more reps wins) over working sets of finished sessions for every
   bodyweight exercise, in chronological order, and inserts a PR row for each
   set that beats the running best and was logged after the current PR.
   achieved_at is set to the set's own created_at (the personal_records table
   has no session/set link column).

Usage
-----
    # Dry run (default): prints the SQL, affected rows and PRs it would insert.
    DATABASE_URL=<your-db-url> python scripts/backfill_bodyweight_prs.py

    # Apply: writes a backup file, then updates and commits.
    DATABASE_URL=<your-db-url> python scripts/backfill_bodyweight_prs.py --apply

Re-running is safe: once no NULL weights remain and the PRs are in place it
finds nothing to do.
"""

import argparse
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from dotenv import load_dotenv
load_dotenv(repo_root / '.env')

import sqlalchemy as sa
from sqlalchemy import text

BODYWEIGHT_EXERCISES = (
    "SELECT id FROM exercises WHERE is_bodyweight = :t AND is_cardio = :f"
)

COUNT_SQL = f"""
SELECT e.name, COUNT(*) AS n
FROM workout_logs wl JOIN exercises e ON e.id = wl.exercise_id
WHERE wl.weight IS NULL AND wl.reps IS NOT NULL
  AND wl.exercise_id IN ({BODYWEIGHT_EXERCISES})
GROUP BY e.name ORDER BY e.name
"""

UPDATE_SQL = f"""
UPDATE workout_logs
SET weight = 0.0
WHERE weight IS NULL
  AND reps IS NOT NULL
  AND exercise_id IN ({BODYWEIGHT_EXERCISES})
"""

# Working sets of finished sessions for bodyweight exercises, oldest first.
# COALESCE so the dry run sees the same values the UPDATE will produce.
SETS_SQL = f"""
SELECT ws.user_id, wl.exercise_id, e.name AS exercise, wl.session_id, wl.set_number,
       COALESCE(wl.weight, 0.0) AS weight, wl.reps, wl.created_at
FROM workout_logs wl
JOIN workout_sessions ws ON ws.id = wl.session_id
JOIN exercises e ON e.id = wl.exercise_id
WHERE ws.end_time IS NOT NULL
  AND wl.set_type = 'working'
  AND wl.reps IS NOT NULL
  AND wl.exercise_id IN ({BODYWEIGHT_EXERCISES})
ORDER BY wl.created_at, wl.id
"""

# The current best PR is the most recently inserted row (highest id), as in the app.
CURRENT_PR_SQL = """
SELECT pr.user_id, pr.exercise_id, pr.weight, pr.reps, pr.achieved_at
FROM personal_records pr
JOIN (SELECT user_id, exercise_id, MAX(id) AS best_id
      FROM personal_records GROUP BY user_id, exercise_id) b
  ON b.best_id = pr.id
"""

INSERT_PR_SQL = """
INSERT INTO personal_records (user_id, exercise_id, weight, reps, achieved_at)
VALUES (:user_id, :exercise_id, :weight, :reps, :achieved_at)
"""

PARAMS = {'t': True, 'f': False}


def engine_from_env():
    url = os.getenv('DATABASE_URL', '')
    if not url:
        sys.exit('ERROR: DATABASE_URL environment variable is not set.')
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    if url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    return sa.create_engine(url)


def beats(weight, reps, best):
    """Same rule as app.update_pr()."""
    if best is None or best['weight'] is None:
        return True
    if weight > best['weight']:
        return True
    return weight == best['weight'] and best['reps'] is not None and reps > best['reps']


def missing_prs(conn):
    current = {
        (r.user_id, r.exercise_id): {'weight': r.weight, 'reps': r.reps, 'achieved_at': r.achieved_at}
        for r in conn.execute(text(CURRENT_PR_SQL))
    }
    new_rows = []
    for s in conn.execute(text(SETS_SQL), PARAMS):
        key = (s.user_id, s.exercise_id)
        best = current.get(key)
        # Only sets logged after the current PR can be a missed PR.
        if best is not None and best['achieved_at'] is not None and s.created_at <= best['achieved_at']:
            continue
        if beats(s.weight, s.reps, best):
            row = {'user_id': s.user_id, 'exercise_id': s.exercise_id, 'weight': s.weight,
                   'reps': s.reps, 'achieved_at': s.created_at}
            new_rows.append((s.exercise, s.session_id, s.set_number, best, row))
            current[key] = row
    return new_rows


def backup(conn):
    def default(o):
        return o.isoformat() if isinstance(o, (datetime, date)) else str(o)

    out = {}
    for table in ('workout_logs', 'personal_records'):
        out[table] = [dict(r._mapping) for r in conn.execute(text(f'SELECT * FROM {table} ORDER BY id'))]
    path = repo_root / f"backup_bodyweight_prs_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(out, default=default, indent=1))
    print(f"Backup written: {path} "
          f"({len(out['workout_logs'])} workout_logs, {len(out['personal_records'])} personal_records)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true', help='back up, then write changes (default: dry run)')
    args = parser.parse_args()

    engine = engine_from_env()
    with engine.connect() as conn:
        print('UPDATE to run:' + UPDATE_SQL.replace(':t', 'TRUE').replace(':f', 'FALSE'))
        counts = conn.execute(text(COUNT_SQL), PARAMS).all()
        print('Bodyweight sets with weight NULL:', sum(c.n for c in counts) or 0)
        for c in counts:
            print(f'  {c.name}: {c.n}')

        rows = missing_prs(conn)
        print(f'\nMissing PRs: {len(rows)}')
        for name, session_id, set_number, old, row in rows:
            was = f"{old['reps']} reps @ {old['weight']} kg" if old else 'none'
            print(f"  {name}: {row['reps']} reps @ {row['weight']} kg "
                  f"(session {session_id}, set {set_number}, {row['achieved_at']}); previous PR: {was}")

        if not args.apply:
            print('\nDry run only. Re-run with --apply to back up and write these changes.')
            return

        backup(conn)
        # The reads above opened a transaction; writes join it and commit together.
        # Any error leaves the connection uncommitted, so it rolls back on close.
        updated = conn.execute(text(UPDATE_SQL), PARAMS).rowcount
        for *_, row in rows:
            conn.execute(text(INSERT_PR_SQL), row)
        conn.commit()
        print(f'\nCommitted: {updated} sets set to 0.0 kg, {len(rows)} PR rows inserted.')


if __name__ == '__main__':
    main()
