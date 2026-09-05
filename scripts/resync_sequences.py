"""One-off repair: fast-forward every table's Postgres id sequence past MAX(id).

Rows inserted with an explicit id (a manual backfill, a database restore) leave
the table's sequence behind the data, so the next auto-generated id collides
with an existing row and the INSERT fails with a duplicate-key error on the
primary key. Run this against the production database to clear that state:

    DATABASE_URL=postgresql://... python scripts/resync_sequences.py

The app also does this on startup, so this script is only needed to repair a
running instance without a redeploy.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db, resync_id_sequence  # noqa: E402
from models import (  # noqa: E402
    User, Exercise, WorkoutSession, WorkoutLog, PersonalRecord, WeightLog,
    BloodworkLog, FoodPreset, ProteinLog, StreakLog, DailySteps,
)

MODELS = [
    User, Exercise, WorkoutSession, WorkoutLog, PersonalRecord, WeightLog,
    BloodworkLog, FoodPreset, ProteinLog, StreakLog, DailySteps,
]


def main():
    with app.app_context():
        if db.engine.dialect.name != 'postgresql':
            print(f'Not a Postgres database ({db.engine.dialect.name}); nothing to do.')
            return
        for model in MODELS:
            ok = resync_id_sequence(model)
            print(f'{model.__tablename__}: {"resynced" if ok else "FAILED"}')


if __name__ == '__main__':
    main()
