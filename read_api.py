"""Read-only JSON API over the workout log.

This module is deliberately read-only: it contains no INSERT/UPDATE/DELETE and
only registers GET routes, so anything holding an API token (a chatbot, a
script) can look at the data but never change it. The MCP layer in
``mcp_server.py`` calls the same ``collect_*`` functions, so both surfaces
always return identical data.

Exposed areas: weight, discipline, nutrition and PRs.
"""

import hmac
import os
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from models import (
    EXERCISE_TYPES,
    FoodPreset,
    PersonalRecord,
    ProteinLog,
    StreakLog,
    User,
    WeightLog,
    db,
    now_amsterdam,
)

read_api = Blueprint('read_api', __name__, url_prefix='/api/v1')

TIMEZONE_NAME = 'Europe/Amsterdam'
PROTEIN_TARGET_G = 140

# The scope every read-only caller gets. Nothing in this app grants more.
READ_SCOPE = 'read'

DEFAULT_WEIGHT_LIMIT = 60
DEFAULT_NUTRITION_DAYS = 7
DEFAULT_DISCIPLINE_HISTORY = 20
MAX_LIMIT = 500


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------

def api_tokens():
    """Static bearer tokens accepted by the API, from the environment.

    ``API_READ_TOKEN`` holds one token, or several separated by commas so an
    old token can stay valid while a new one is rolled out.
    """
    raw = os.getenv('API_READ_TOKEN', '')
    return [t.strip() for t in raw.split(',') if t.strip()]


def check_static_token(token):
    """Compare a presented token against the configured ones in constant time."""
    return any(hmac.compare_digest(token, valid) for valid in api_tokens())


def bearer_token_from_request():
    """Pull the token out of the Authorization header, or the X-API-Key header."""
    header = request.headers.get('Authorization', '')
    if header.lower().startswith('bearer '):
        return header[7:].strip()
    return request.headers.get('X-API-Key', '').strip()


def api_user():
    """The user whose data the API exposes.

    This is a single-user app, so a valid token maps to the admin account
    (overridable with ``API_USER``) rather than to a per-caller identity.
    """
    username = os.getenv('API_USER') or os.getenv('ADMIN_USERNAME', 'admin')
    user = User.query.filter_by(username=username).first()
    if user is None:
        # Fall back to the only account if the configured name doesn't match,
        # so a renamed admin doesn't silently break the API.
        user = User.query.order_by(User.id).first()
    return user


def authenticate():
    """Return ``(user, None)`` on success or ``(None, error_response)`` on failure."""
    token = bearer_token_from_request()
    if not token:
        return None, unauthorized('Missing bearer token')

    if not check_static_token(token):
        # Fall back to an OAuth access token issued by our own /oauth/token.
        from mcp_oauth import verify_access_token

        claims = verify_access_token(token)
        if claims is None:
            return None, unauthorized('Invalid or expired token')
        user = User.query.get(claims['user_id'])
        if user is None:
            return None, unauthorized('Token refers to an unknown user')
        return user, None

    user = api_user()
    if user is None:
        return None, unauthorized('No user exists in this database')
    return user, None


def unauthorized(message):
    response = jsonify({'error': 'unauthorized', 'message': message})
    response.status_code = 401
    response.headers['WWW-Authenticate'] = 'Bearer realm="workout-api"'
    return response


def token_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        from mcp_oauth import oauth_enabled

        if not api_tokens() and not oauth_enabled():
            return jsonify({
                'error': 'not_configured',
                'message': 'Set API_READ_TOKEN (or enable OAuth) to use the read API.',
            }), 503
        user, error = authenticate()
        if error is not None:
            return error
        return view(user, *args, **kwargs)

    return wrapper


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def iso(dt):
    """Serialize a stored (naive, Amsterdam local) datetime."""
    if dt is None:
        return None
    return dt.isoformat()


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
    """Epley estimate, so a chatbot can compare PRs at different rep counts."""
    if not weight or not reps:
        return None
    return round(weight * (1 + reps / 30.0), 1)


# --------------------------------------------------------------------------
# Data collection - shared by the REST routes and the MCP tools
# --------------------------------------------------------------------------

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
    oldest_in_window = entries[-1] if entries else None

    change_kg = None
    if latest and oldest_in_window and latest is not oldest_in_window:
        change_kg = round(latest['weight_kg'] - oldest_in_window['weight_kg'], 2)

    total_count = WeightLog.query.filter_by(user_id=user_id).count()

    return {
        'timezone': TIMEZONE_NAME,
        'latest': latest,
        'entries': entries,
        'summary': {
            'entries_returned': len(entries),
            'entries_total': total_count,
            'change_kg_over_window': change_kg,
            'window_start': oldest_in_window['logged_at'] if oldest_in_window else None,
            'window_end': latest['logged_at'] if latest else None,
        },
    }


def collect_discipline(user_id, history_limit=DEFAULT_DISCIPLINE_HISTORY):
    """Current NoFap/NoPorn streak plus lifetime stats and past attempts."""
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

    milestones = [
        (1, 'First Blood'), (3, 'Three Days'), (7, 'One Week'), (14, 'Two Weeks'),
        (30, 'The Month'), (60, 'Two Months'), (90, 'The Reboot'),
        (180, 'Half Year'), (365, 'Monk Mode'),
    ]
    next_milestone = next(({'days': d, 'name': n, 'days_to_go': d - current_days}
                           for d, n in milestones if d > current_days), None)

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
        'milestones_reached': [n for d, n in milestones if current_days >= d],
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
    """Protein intake: today's logs, a per-day breakdown and a 30-day average."""
    today = now_amsterdam().date()
    today_start = start_of_today()
    today_end = today_start + timedelta(days=1)

    today_logs = (ProteinLog.query
                  .filter(ProteinLog.user_id == user_id,
                          ProteinLog.logged_at >= today_start,
                          ProteinLog.logged_at < today_end)
                  .order_by(ProteinLog.logged_at.desc())
                  .all())
    today_total = round(sum(log.protein_g for log in today_logs), 1)

    window_start = today_start - timedelta(days=days - 1)
    window_logs = (ProteinLog.query
                   .filter(ProteinLog.user_id == user_id,
                           ProteinLog.logged_at >= window_start)
                   .all())
    per_day = defaultdict(float)
    for log in window_logs:
        per_day[log.logged_at.date()] += log.protein_g

    daily = [{
        'date': (today - timedelta(days=days - 1 - i)).isoformat(),
        'total_protein_g': round(per_day.get(today - timedelta(days=days - 1 - i), 0.0), 1),
    } for i in range(days)]

    # 30-day average over the days that actually have logs, matching the page.
    month_start = today_start - timedelta(days=29)
    month_logs = (ProteinLog.query
                  .filter(ProteinLog.user_id == user_id,
                          ProteinLog.logged_at >= month_start)
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
        'thirty_day': {
            'average_protein_g': avg_30,
            'days_logged': days_logged_30,
        },
        'presets': [{
            'id': p.id,
            'name': p.name,
            'protein_per_serving_g': p.protein_per_serving,
            'serving_unit': p.serving_unit,
        } for p in presets],
    }


def collect_prs(user_id, exercise=None):
    """Current personal records, grouped by exercise type like the PRs page."""
    # update_pr() only inserts on a strict improvement, so the highest id per
    # exercise is that exercise's current best.
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

    ordered = []
    for ex_type in EXERCISE_TYPES:
        if ex_type in grouped:
            ordered.append({'type': ex_type, 'records': sorted(grouped[ex_type],
                                                               key=lambda r: r['exercise'])})
    for ex_type, prs in grouped.items():
        if ex_type not in EXERCISE_TYPES:
            ordered.append({'type': ex_type, 'records': sorted(prs, key=lambda r: r['exercise'])})

    return {
        'timezone': TIMEZONE_NAME,
        'filter': exercise,
        'total_records': sum(len(g['records']) for g in ordered),
        'groups': ordered,
    }


# --------------------------------------------------------------------------
# Routes (GET only - this API never writes)
# --------------------------------------------------------------------------

@read_api.route('/weight', methods=['GET'])
@token_required
def weight_endpoint(user):
    limit = clamp_int(request.args.get('limit'), DEFAULT_WEIGHT_LIMIT)
    return jsonify(collect_weight(user.id, limit))


@read_api.route('/discipline', methods=['GET'])
@token_required
def discipline_endpoint(user):
    limit = clamp_int(request.args.get('limit'), DEFAULT_DISCIPLINE_HISTORY, maximum=200)
    return jsonify(collect_discipline(user.id, limit))


@read_api.route('/nutrition', methods=['GET'])
@token_required
def nutrition_endpoint(user):
    days = clamp_int(request.args.get('days'), DEFAULT_NUTRITION_DAYS, maximum=90)
    return jsonify(collect_nutrition(user.id, days))


@read_api.route('/prs', methods=['GET'])
@token_required
def prs_endpoint(user):
    return jsonify(collect_prs(user.id, request.args.get('exercise')))


@read_api.route('/ping', methods=['GET'])
@token_required
def ping_endpoint(user):
    """Cheap authenticated check that a token works."""
    return jsonify({
        'ok': True,
        'user': user.username,
        'scope': READ_SCOPE,
        'server_time': iso(now_amsterdam()),
        'timezone': TIMEZONE_NAME,
    })
