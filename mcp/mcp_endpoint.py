"""Model Context Protocol endpoint.

Speaks the Streamable HTTP transport at ``POST /mcp`` in stateless mode: each
JSON-RPC request gets a plain JSON response, so there is no session held in
memory and the service can restart without breaking a connected client.

Every tool is a read. There is no tool that writes, and the collectors in
``data.py`` only issue SELECTs, so a connected chatbot cannot modify the log.
"""

import json

from flask import Blueprint, current_app, jsonify, request

import config
from auth import authenticate
from data import (
    DEFAULT_DISCIPLINE_HISTORY,
    DEFAULT_NUTRITION_DAYS,
    DEFAULT_STEP_DAYS,
    DEFAULT_WEIGHT_LIMIT,
    DEFAULT_WORKOUT_DAYS,
    DEFAULT_WORKOUT_SESSIONS,
    clamp_int,
    collect_discipline,
    collect_nutrition,
    collect_prs,
    collect_steps,
    collect_weight,
    collect_workouts,
)

mcp_bp = Blueprint('mcp', __name__)

SERVER_NAME = 'workout-log'
SERVER_VERSION = '1.0.0'

# Protocol revisions this server can speak, newest first.
SUPPORTED_PROTOCOL_VERSIONS = ['2025-06-18', '2025-03-26', '2024-11-05']
DEFAULT_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

READ_ONLY_HINTS = {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False}

TOOLS = [
    {
        'name': 'get_workouts',
        'title': 'Workout history',
        'description': (
            'Read the training log itself: the workout sessions performed in a '
            'recent window, each with its individual sets - exercise, reps, weight, '
            'warmup vs working, cardio calories and time - plus per-session volume '
            'and a summary of which exercises were trained and how often. Use this '
            'for anything about what was actually done or when ("did I train squats '
            'this week", "how many sessions last month", "how heavy did I squat on '
            "Tuesday\"). Filter by exercise to answer questions about one lift. "
            'get_personal_records is only the all-time best per exercise, so it '
            'cannot say whether something was trained recently.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'days': {
                    'type': 'integer',
                    'description': f'How many days back to look, ending today (1-365, default {DEFAULT_WORKOUT_DAYS}).',
                    'minimum': 1, 'maximum': 365,
                },
                'exercise': {
                    'type': 'string',
                    'description': 'Optional case-insensitive substring of an exercise name, e.g. "squat". Returns only sessions containing it, with the matching sets.',
                },
                'limit': {
                    'type': 'integer',
                    'description': f'Maximum sessions to return, newest first (1-100, default {DEFAULT_WORKOUT_SESSIONS}).',
                    'minimum': 1, 'maximum': 100,
                },
            },
            'additionalProperties': False,
        },
        'annotations': READ_ONLY_HINTS,
    },
    {
        'name': 'get_weight',
        'title': 'Weight history',
        'description': (
            'Read the weight page: body weight in kg, body fat percentage, visceral '
            'fat and notes, newest entry first, plus the change over the window.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'limit': {
                    'type': 'integer',
                    'description': f'How many entries to return (1-500, default {DEFAULT_WEIGHT_LIMIT}).',
                    'minimum': 1, 'maximum': 500,
                },
            },
            'additionalProperties': False,
        },
        'annotations': READ_ONLY_HINTS,
    },
    {
        'name': 'get_discipline',
        'title': 'Discipline streak',
        'description': (
            'Read the discipline page: current streak in days and when it started, '
            'best streak, total clean days, milestones reached, the next milestone '
            'and past attempts with their relapse notes.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'history_limit': {
                    'type': 'integer',
                    'description': f'How many past attempts to include (1-200, default {DEFAULT_DISCIPLINE_HISTORY}).',
                    'minimum': 1, 'maximum': 200,
                },
            },
            'additionalProperties': False,
        },
        'annotations': READ_ONLY_HINTS,
    },
    {
        'name': 'get_nutrition',
        'title': 'Protein / nutrition log',
        'description': (
            "Read the nutrition page: today's protein entries and total against the "
            'daily target, per-day totals for the recent window, the 30-day average '
            'and the saved food presets.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'days': {
                    'type': 'integer',
                    'description': f'Days of per-day totals to return (1-90, default {DEFAULT_NUTRITION_DAYS}).',
                    'minimum': 1, 'maximum': 90,
                },
            },
            'additionalProperties': False,
        },
        'annotations': READ_ONLY_HINTS,
    },
    {
        'name': 'get_steps',
        'title': 'Daily steps',
        'description': (
            "Read the daily step counts logged on the workout page: today's steps, "
            'the 7-day and 30-day averages, and the per-day series. Averages cover '
            'only the days that have an entry, so a day that was never logged reads '
            'as unknown rather than as zero steps.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'days': {
                    'type': 'integer',
                    'description': f'How many days back to return, ending today (1-365, default {DEFAULT_STEP_DAYS}).',
                    'minimum': 1, 'maximum': 365,
                },
            },
            'additionalProperties': False,
        },
        'annotations': READ_ONLY_HINTS,
    },
    {
        'name': 'get_personal_records',
        'title': 'Personal records',
        'description': (
            'Read the PRs page: the current personal record per exercise grouped by '
            'exercise type, with weight, reps, an estimated 1RM, cardio calories and '
            'time, and when each was achieved. These are all-time bests, not a '
            'training history - use get_workouts to see what was actually performed '
            'on a given day or in a recent window.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'exercise': {
                    'type': 'string',
                    'description': 'Optional case-insensitive substring filtering exercise names, e.g. "bench".',
                },
            },
            'additionalProperties': False,
        },
        'annotations': READ_ONLY_HINTS,
    },
]


def run_tool(name, arguments, user):
    """Dispatch a tool call to its read-only collector."""
    arguments = arguments or {}

    if name == 'get_workouts':
        exercise = arguments.get('exercise')
        return collect_workouts(
            user.id,
            days=clamp_int(arguments.get('days'), DEFAULT_WORKOUT_DAYS, maximum=365),
            exercise=exercise if isinstance(exercise, str) else None,
            limit=clamp_int(arguments.get('limit'), DEFAULT_WORKOUT_SESSIONS, maximum=100))
    if name == 'get_weight':
        return collect_weight(user.id, clamp_int(arguments.get('limit'), DEFAULT_WEIGHT_LIMIT))
    if name == 'get_discipline':
        return collect_discipline(
            user.id,
            clamp_int(arguments.get('history_limit'), DEFAULT_DISCIPLINE_HISTORY, maximum=200))
    if name == 'get_nutrition':
        return collect_nutrition(
            user.id, clamp_int(arguments.get('days'), DEFAULT_NUTRITION_DAYS, maximum=90))
    if name == 'get_steps':
        return collect_steps(user.id, clamp_int(arguments.get('days'), DEFAULT_STEP_DAYS, maximum=365))
    if name == 'get_personal_records':
        exercise = arguments.get('exercise')
        return collect_prs(user.id, exercise if isinstance(exercise, str) else None)

    raise KeyError(name)


def _result(request_id, result):
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def _error(request_id, code, message):
    return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}


def handle_message(message, user):
    """Handle one JSON-RPC message; returns None for notifications."""
    if not isinstance(message, dict):
        return _error(None, INVALID_REQUEST, 'Request must be a JSON-RPC object')

    method = message.get('method')
    request_id = message.get('id')
    params = message.get('params') or {}

    if method == 'initialize':
        requested = params.get('protocolVersion')
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
        return _result(request_id, {
            'protocolVersion': version,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': SERVER_NAME, 'version': SERVER_VERSION},
            'instructions': (
                'Read-only access to a personal workout log. get_workouts is the '
                'training history (sessions and sets actually performed); '
                'get_personal_records is the all-time best per exercise; '
                'get_weight, get_discipline, get_nutrition and get_steps cover '
                'body weight, streaks, protein and daily steps. Nothing here can '
                'change the log.'
            ),
        })

    if method in ('notifications/initialized', 'notifications/cancelled'):
        return None

    if method == 'ping':
        return _result(request_id, {})

    if method == 'tools/list':
        return _result(request_id, {'tools': TOOLS})

    if method == 'tools/call':
        name = params.get('name')
        try:
            payload = run_tool(name, params.get('arguments'), user)
        except KeyError:
            return _error(request_id, INVALID_PARAMS, f'Unknown tool: {name}')
        except Exception:
            current_app.logger.exception('MCP tool %s failed', name)
            # Tool failures are reported in-band so the model can react to them.
            return _result(request_id, {
                'content': [{'type': 'text', 'text': f'Failed to read {name}.'}],
                'isError': True,
            })
        return _result(request_id, {
            'content': [{'type': 'text', 'text': json.dumps(payload, indent=2, default=str)}],
            'structuredContent': payload,
            'isError': False,
        })

    if method in ('resources/list', 'prompts/list'):
        # Not declared in capabilities, but some clients probe anyway.
        return _error(request_id, METHOD_NOT_FOUND, f'{method} is not supported')

    if 'id' not in message:
        return None
    return _error(request_id, METHOD_NOT_FOUND, f'Unknown method: {method}')


@mcp_bp.route('/mcp', methods=['POST'])
def mcp_endpoint():
    if not config.mcp_enabled():
        return jsonify({'error': 'disabled',
                        'message': 'Set MCP_ENABLED=1 to enable this endpoint'}), 404

    user, error = authenticate()
    if error is not None:
        return error

    message = request.get_json(silent=True)
    if message is None:
        return jsonify(_error(None, PARSE_ERROR, 'Request body must be JSON')), 400

    if isinstance(message, list):
        # Batches were dropped in the 2025-06-18 revision, but older clients
        # may still send one.
        responses = [r for r in (handle_message(m, user) for m in message) if r is not None]
        return jsonify(responses) if responses else ('', 202)

    response = handle_message(message, user)
    return jsonify(response) if response is not None else ('', 202)


@mcp_bp.route('/mcp', methods=['GET', 'DELETE'])
def mcp_no_stream():
    """No server-initiated stream, and no session state to delete."""
    if not config.mcp_enabled():
        return jsonify({'error': 'disabled'}), 404
    user, error = authenticate()
    if error is not None:
        return error
    if request.method == 'DELETE':
        return '', 204
    return jsonify(_error(None, METHOD_NOT_FOUND,
                          'This server is stateless; SSE streams are not offered')), 405
