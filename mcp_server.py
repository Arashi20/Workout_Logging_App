"""Model Context Protocol server exposing the app's data read-only.

Speaks the Streamable HTTP transport at ``POST /mcp`` in stateless mode: each
JSON-RPC request is answered with a plain JSON response, so there is no session
to keep in memory and the app can be restarted or scaled without breaking a
connected client.

Every tool here is a read. There is no tool that writes, and the underlying
``collect_*`` helpers in ``read_api`` only issue SELECTs, so a connected
chatbot cannot modify the log even if it tries.
"""

import json
import os

from flask import Blueprint, current_app, jsonify, request

from models import User
from read_api import (
    DEFAULT_DISCIPLINE_HISTORY,
    DEFAULT_NUTRITION_DAYS,
    DEFAULT_WEIGHT_LIMIT,
    api_user,
    check_static_token,
    clamp_int,
    collect_discipline,
    collect_nutrition,
    collect_prs,
    collect_weight,
)

mcp_bp = Blueprint('mcp', __name__)

SERVER_NAME = 'workout-log'
SERVER_VERSION = '1.0.0'

# Protocol revisions this server can speak, newest first.
SUPPORTED_PROTOCOL_VERSIONS = ['2025-06-18', '2025-03-26', '2024-11-05']
DEFAULT_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def mcp_enabled():
    return os.getenv('MCP_ENABLED', '1').lower() in ('1', 'true', 'yes')


# --------------------------------------------------------------------------
# Tool definitions
# --------------------------------------------------------------------------

READ_ONLY_HINTS = {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False}

TOOLS = [
    {
        'name': 'get_weight',
        'title': 'Weight history',
        'description': (
            'Read the body weight page: body weight in kg, body fat percentage, '
            'visceral fat and notes, newest entry first, plus the change over the '
            'returned window.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'limit': {
                    'type': 'integer',
                    'description': f'How many entries to return (1-500, default {DEFAULT_WEIGHT_LIMIT}).',
                    'minimum': 1,
                    'maximum': 500,
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
            'Read the discipline page: the current streak in days and when it started, '
            'best streak, total clean days, milestones reached, the next milestone and '
            'past attempts with their relapse notes.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'history_limit': {
                    'type': 'integer',
                    'description': f'How many past attempts to include (1-200, default {DEFAULT_DISCIPLINE_HISTORY}).',
                    'minimum': 1,
                    'maximum': 200,
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
            'daily target, a per-day total for the recent window, the 30-day average '
            'and the saved food presets.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'days': {
                    'type': 'integer',
                    'description': f'Days of per-day totals to return (1-90, default {DEFAULT_NUTRITION_DAYS}).',
                    'minimum': 1,
                    'maximum': 90,
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
            'exercise type, with weight, reps, an estimated 1RM, cardio calories/time '
            'and when each was achieved.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'exercise': {
                    'type': 'string',
                    'description': 'Optional case-insensitive substring to filter exercise names, e.g. "bench".',
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

    if name == 'get_weight':
        return collect_weight(user.id, clamp_int(arguments.get('limit'), DEFAULT_WEIGHT_LIMIT))
    if name == 'get_discipline':
        return collect_discipline(
            user.id,
            clamp_int(arguments.get('history_limit'), DEFAULT_DISCIPLINE_HISTORY, maximum=200),
        )
    if name == 'get_nutrition':
        return collect_nutrition(
            user.id, clamp_int(arguments.get('days'), DEFAULT_NUTRITION_DAYS, maximum=90)
        )
    if name == 'get_personal_records':
        exercise = arguments.get('exercise')
        return collect_prs(user.id, exercise if isinstance(exercise, str) else None)

    raise KeyError(name)


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------

def _bearer_token():
    header = request.headers.get('Authorization', '')
    if header.lower().startswith('bearer '):
        return header[7:].strip()
    return ''


def authenticate_mcp():
    """Return ``(user, None)`` or ``(None, response)`` with a 401 challenge."""
    token = _bearer_token()
    if not token:
        return None, _challenge('Missing bearer token')

    if check_static_token(token):
        user = api_user()
        if user is None:
            return None, _challenge('No user exists in this database')
        return user, None

    from mcp_oauth import oauth_enabled, verify_access_token

    if oauth_enabled():
        claims = verify_access_token(token)
        if claims is not None:
            user = User.query.get(claims['user_id'])
            if user is not None:
                return user, None

    return None, _challenge('Invalid or expired token')


def _challenge(message):
    """401 that points the client at our OAuth metadata (RFC 9728)."""
    from mcp_oauth import public_base_url

    response = jsonify({'error': 'unauthorized', 'message': message})
    response.status_code = 401
    resource_metadata = f'{public_base_url()}/.well-known/oauth-protected-resource'
    response.headers['WWW-Authenticate'] = (
        f'Bearer realm="workout-log", resource_metadata="{resource_metadata}"'
    )
    return response


# --------------------------------------------------------------------------
# JSON-RPC plumbing
# --------------------------------------------------------------------------

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
    is_notification = 'id' not in message

    if method == 'initialize':
        requested = params.get('protocolVersion')
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
        return _result(request_id, {
            'protocolVersion': version,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': SERVER_NAME, 'version': SERVER_VERSION},
            'instructions': (
                'Read-only access to a personal workout log. Use get_weight, '
                'get_discipline, get_nutrition and get_personal_records to look up '
                'the data. Nothing here can change the log.'
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
        # Declared unsupported in capabilities, but some clients probe anyway.
        return _error(request_id, METHOD_NOT_FOUND, f'{method} is not supported')

    if is_notification:
        return None
    return _error(request_id, METHOD_NOT_FOUND, f'Unknown method: {method}')


@mcp_bp.route('/mcp', methods=['POST'])
def mcp_endpoint():
    if not mcp_enabled():
        return jsonify({'error': 'disabled',
                        'message': 'Set MCP_ENABLED=1 to enable the MCP endpoint'}), 404

    user, challenge = authenticate_mcp()
    if challenge is not None:
        return challenge

    message = request.get_json(silent=True)
    if message is None:
        return jsonify(_error(None, PARSE_ERROR, 'Request body must be JSON')), 400

    if isinstance(message, list):
        # JSON-RPC batches were dropped in the 2025-06-18 revision, but older
        # clients may still send one.
        responses = [r for r in (handle_message(m, user) for m in message) if r is not None]
        if not responses:
            return '', 202
        return jsonify(responses)

    response = handle_message(message, user)
    if response is None:
        return '', 202
    return jsonify(response)


@mcp_bp.route('/mcp', methods=['GET', 'DELETE'])
def mcp_unsupported_transport():
    """No server-initiated stream and no session state to delete."""
    if not mcp_enabled():
        return jsonify({'error': 'disabled'}), 404
    user, challenge = authenticate_mcp()
    if challenge is not None:
        return challenge
    if request.method == 'DELETE':
        return '', 204
    return jsonify(_error(None, METHOD_NOT_FOUND,
                          'This server is stateless; SSE streams are not offered')), 405
