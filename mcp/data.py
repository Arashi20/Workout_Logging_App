"""The read queries behind every tool and endpoint.

Nothing in this module writes: it issues SELECTs and shapes the rows into JSON.
Both the MCP tools and the REST endpoints call these functions, so the two
surfaces can never drift apart.
"""

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func

from config import TIMEZONE_NAME, now_amsterdam
from models import (
    EXERCISE_TYPES,
    FoodPreset,
    PersonalRecord,
    ProteinLog,
    StreakLog,
    WeightLog,
    db,
)

PROTEIN_TARGET_G = 140

DEFAULT_WEIGHT_LIMIT = 60
DEFAULT_NUTRITION_DAYS = 7
DEFAULT_DISCIPLINE_HISTORY = 20
MAX_LIMIT = 500

MILESTONES = [
    (1, 'First Blood'), (3, 'Three Days'), (7, 'One Week'), (14, 'Two Weeks'),
    (30, 'The Month'), (60, 'Two Months'), (90, 'The Reboot'),
    (180, 'Half Year'), (365, 'Monk Mode'),
]


def iso(dt):
    """Serialize a stored (naive, Amsterdam local) datetime."""
    return dt.isoformat() if dt is not None else None


def clamp_int(raw, default, minimum=1, maximum=MAX_LIMIT):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def start_of_today():
    today = now_amsterdam().date()
    return datetime(today.year, today.month, today.day)


def estimated_one_rm(weight, reps):
    """Epley estimate, so PRs at different rep counts can be compared."""
    if not weight or not reps:
        return None
    return round(weight * (1 + reps / 30.0), 1)


def collect_weight(user_id, limit=DEFAULT_WEIGHT_LIMIT):
    """Body weight / body fat / visceral fat history, newest first."""
    logs = (WeightLog.query
            .filter_by(user_id=user_id)
            .order_by(WeightLog.logged_at.desc())
            .limit(limit)
            .all())

    entries = [{
        'id': log.id,
        'logged_at': iso(log.logged_at),
        'weight_kg': log.weight,
        'body_fat_percentage': log.body_fat_percentage,
        'visceral_fat': log.visceral_fat,
        'notes': log.notes,
    } for log in logs]

    latest = entries[0] if entries else None
    oldest = entries[-1] if entries else None
    change_kg = None
    if latest and oldest and latest is not oldest:
        change_kg = round(latest['weight_kg'] - oldest['weight_kg'], 2)

    return {
        'timezone': TIMEZONE_NAME,
        'latest': latest,
        'entries': entries,
        'summary': {
            'entries_returned': len(entries),
            'entries_total': WeightLog.query.filter_by(user_id=user_id).count(),
            'change_kg_over_window': change_kg,
            'window_start': oldest['logged_at'] if oldest else None,
            'window_end': latest['logged_at'] if latest else None,
        },
    }


def collect_discipline(user_id, history_limit=DEFAULT_DISCIPLINE_HISTORY):
    """Current streak plus lifetime stats and past attempts."""
    logs = (StreakLog.query
            .filter_by(user_id=user_id)
            .order_by(StreakLog.start_date.desc())
            .all())
    now = now_amsterdam()

    active = next((l for l in logs if l.end_date is None), None)
    current_days = (now - active.start_date).days if active else 0

    completed = [l for l in logs if l.end_date is not None]
    completed_days = [(l.end_date - l.start_date).days for l in completed]
    all_days = completed_days + ([current_days] if active else [])

    next_milestone = next(({'days': d, 'name': n, 'days_to_go': d - current_days}
                           for d, n in MILESTONES if d > current_days), None)

    return {
        'timezone': TIMEZONE_NAME,
        'as_of': iso(now),
        'current_streak': {
            'active': active is not None,
            'days': current_days,
            'started_at': iso(active.start_date) if active else None,
        },
        'stats': {
            'best_streak_days': max(all_days) if all_days else 0,
            'total_clean_days': sum(completed_days) + current_days,
            'total_attempts': len(logs),
        },
        'milestones_reached': [n for d, n in MILESTONES if current_days >= d],
        'next_milestone': next_milestone,
        'history': [{
            'id': l.id,
            'started_at': iso(l.start_date),
            'ended_at': iso(l.end_date),
            'days': (l.end_date - l.start_date).days,
            'relapse_note': l.relapse_note,
        } for l in sorted(completed, key=lambda l: l.start_date, reverse=True)[:history_limit]],
        'history_total': len(completed),
    }


def collect_nutrition(user_id, days=DEFAULT_NUTRITION_DAYS):
    """Protein intake: today's entries, per-day totals and a 30-day average."""
    today = now_amsterdam().date()
    today_start = start_of_today()

    today_logs = (ProteinLog.query
                  .filter(ProteinLog.user_id == user_id,
                          ProteinLog.logged_at >= today_start,
                          ProteinLog.logged_at < today_start + timedelta(days=1))
                  .order_by(ProteinLog.logged_at.desc())
                  .all())
    today_total = round(sum(log.protein_g for log in today_logs), 1)

    window_logs = (ProteinLog.query
                   .filter(ProteinLog.user_id == user_id,
                           ProteinLog.logged_at >= today_start - timedelta(days=days - 1))
                   .all())
    per_day = defaultdict(float)
    for log in window_logs:
        per_day[log.logged_at.date()] += log.protein_g

    daily = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        daily.append({'date': day.isoformat(),
                      'total_protein_g': round(per_day.get(day, 0.0), 1)})

    # 30-day average over the days that actually have logs, matching the page.
    month_logs = (ProteinLog.query
                  .filter(ProteinLog.user_id == user_id,
                          ProteinLog.logged_at >= today_start - timedelta(days=29))
                  .all())
    month_totals = defaultdict(float)
    for log in month_logs:
        month_totals[log.logged_at.date()] += log.protein_g
    days_logged_30 = len(month_totals)
    avg_30 = round(sum(month_totals.values()) / days_logged_30, 1) if days_logged_30 else 0.0

    presets = (FoodPreset.query
               .filter_by(user_id=user_id)
               .order_by(FoodPreset.name)
               .all())

    return {
        'timezone': TIMEZONE_NAME,
        'date': today.isoformat(),
        'protein_target_g': PROTEIN_TARGET_G,
        'today': {
            'total_protein_g': today_total,
            'target_progress_pct': round(min(today_total / PROTEIN_TARGET_G * 100, 100), 1),
            'remaining_g': round(max(PROTEIN_TARGET_G - today_total, 0), 1),
            'entries': [{
                'id': log.id,
                'food_name': log.food_name,
                'protein_g': log.protein_g,
                'logged_at': iso(log.logged_at),
            } for log in today_logs],
        },
        'daily_totals': daily,
        'thirty_day': {'average_protein_g': avg_30, 'days_logged': days_logged_30},
        'presets': [{
            'id': p.id,
            'name': p.name,
            'protein_per_serving_g': p.protein_per_serving,
            'serving_unit': p.serving_unit,
        } for p in presets],
    }


def collect_prs(user_id, exercise=None):
    """Current personal records, grouped by exercise type like the PRs page."""
    # The main app only inserts a PR row on a strict improvement, so the highest
    # id per exercise is that exercise's current best.
    best_subq = (db.session.query(func.max(PersonalRecord.id).label('best_id'))
                 .filter(PersonalRecord.user_id == user_id)
                 .group_by(PersonalRecord.exercise_id)
                 .subquery())

    records = (PersonalRecord.query
               .join(best_subq, PersonalRecord.id == best_subq.c.best_id)
               .all())

    if exercise:
        needle = exercise.strip().lower()
        records = [r for r in records if needle in (r.exercise.name or '').lower()]

    grouped = defaultdict(list)
    for pr in records:
        grouped[pr.exercise.exercise_type or 'Uncategorized'].append({
            'exercise': pr.exercise.name,
            'exercise_id': pr.exercise_id,
            'is_cardio': pr.exercise.is_cardio,
            'is_bodyweight': pr.exercise.is_bodyweight,
            'weight_kg': pr.weight,
            'reps': pr.reps,
            'estimated_one_rm_kg': estimated_one_rm(pr.weight, pr.reps),
            'calories': pr.calories,
            'time_minutes': pr.time_minutes,
            'achieved_at': iso(pr.achieved_at),
        })

    ordered = [{'type': t, 'records': sorted(grouped[t], key=lambda r: r['exercise'])}
               for t in EXERCISE_TYPES if t in grouped]
    ordered += [{'type': t, 'records': sorted(rs, key=lambda r: r['exercise'])}
                for t, rs in grouped.items() if t not in EXERCISE_TYPES]

    return {
        'timezone': TIMEZONE_NAME,
        'filter': exercise,
        'total_records': sum(len(g['records']) for g in ordered),
        'groups': ordered,
    }
