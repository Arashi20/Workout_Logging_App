"""Plain REST view of the same data, for curl and scripts.

GET only - there is no route here that writes.
"""

from flask import Blueprint, jsonify, request

from auth import token_required
from config import TIMEZONE_NAME, now_amsterdam
from data import (
    DEFAULT_DISCIPLINE_HISTORY,
    DEFAULT_NUTRITION_DAYS,
    DEFAULT_WEIGHT_LIMIT,
    DEFAULT_WORKOUT_DAYS,
    DEFAULT_WORKOUT_SESSIONS,
    clamp_int,
    collect_discipline,
    collect_nutrition,
    collect_prs,
    collect_weight,
    collect_workouts,
    iso,
)

rest_api = Blueprint('rest_api', __name__, url_prefix='/api/v1')


@rest_api.route('/workouts', methods=['GET'])
@token_required
def workouts_endpoint(user):
    return jsonify(collect_workouts(
        user.id,
        days=clamp_int(request.args.get('days'), DEFAULT_WORKOUT_DAYS, maximum=365),
        exercise=request.args.get('exercise'),
        limit=clamp_int(request.args.get('limit'), DEFAULT_WORKOUT_SESSIONS, maximum=100)))


@rest_api.route('/weight', methods=['GET'])
@token_required
def weight_endpoint(user):
    return jsonify(collect_weight(user.id, clamp_int(request.args.get('limit'),
                                                     DEFAULT_WEIGHT_LIMIT)))


@rest_api.route('/discipline', methods=['GET'])
@token_required
def discipline_endpoint(user):
    limit = clamp_int(request.args.get('limit'), DEFAULT_DISCIPLINE_HISTORY, maximum=200)
    return jsonify(collect_discipline(user.id, limit))


@rest_api.route('/nutrition', methods=['GET'])
@token_required
def nutrition_endpoint(user):
    days = clamp_int(request.args.get('days'), DEFAULT_NUTRITION_DAYS, maximum=90)
    return jsonify(collect_nutrition(user.id, days))


@rest_api.route('/prs', methods=['GET'])
@token_required
def prs_endpoint(user):
    return jsonify(collect_prs(user.id, request.args.get('exercise')))


@rest_api.route('/ping', methods=['GET'])
@token_required
def ping_endpoint(user):
    """Cheap authenticated check that a token works."""
    return jsonify({
        'ok': True,
        'user': user.username,
        'scope': 'read',
        'server_time': iso(now_amsterdam()),
        'timezone': TIMEZONE_NAME,
    })
