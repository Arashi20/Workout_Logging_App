"""OAuth 2.1 authorization server for the Claude custom connector.

Claude's custom connectors authenticate with OAuth, so this implements the
slice of OAuth 2.1 a remote MCP server needs:

  * RFC 8414 authorization-server metadata and RFC 9728 protected-resource
    metadata, so Claude discovers the endpoints on its own;
  * RFC 7591 dynamic client registration (Claude registers itself), plus an
    optional pre-shared client from MCP_OAUTH_CLIENT_ID / _CLIENT_SECRET;
  * authorization code with PKCE (S256), and refresh tokens.

Users sign in with their normal app username and password, checked against the
shared users table. Codes, tokens and client secrets are HMAC-signed values
derived from the signing key rather than database rows, so this service needs
no tables of its own; rotating the key revokes everything it has issued.
"""

import hashlib
import hmac
import os
import secrets
import time
from base64 import urlsafe_b64encode
from urllib.parse import urlencode, urlparse

from flask import (
    Blueprint,
    current_app,
    jsonify,
    make_response,
    redirect,
    render_template_string,
    request,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash

import config
from models import User

oauth_bp = Blueprint('oauth', __name__)

# Where Claude sends the browser back after approval. Kept as the default
# allow-list so a pre-shared client works without extra configuration.
DEFAULT_REDIRECT_URIS = [
    'https://claude.ai/api/mcp/auth_callback',
    'https://claude.com/api/mcp/auth_callback',
]

AUTH_CODE_TTL = 300                    # seconds; codes are single use
ACCESS_TOKEN_TTL = 3600                # 1 hour
REFRESH_TOKEN_TTL = 60 * 60 * 24 * 30  # 30 days
READ_SCOPE = 'read'

# Codes already exchanged, so a replay inside the TTL fails. In-process only,
# which covers a single-worker deployment; a code surviving a restart is still
# bounded by AUTH_CODE_TTL.
_used_codes = set()


def _serializer(salt):
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=salt)


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------

def static_client():
    """The optional pre-shared client configured through the environment."""
    client_id = os.getenv('MCP_OAUTH_CLIENT_ID')
    if not client_id:
        return None
    return {
        'client_id': client_id,
        'client_secret': os.getenv('MCP_OAUTH_CLIENT_SECRET'),
        'redirect_uris': config.csv_env('MCP_OAUTH_REDIRECT_URIS') or list(DEFAULT_REDIRECT_URIS),
    }


def derive_client_secret(client_id):
    key = current_app.config['SECRET_KEY'].encode()
    digest = hmac.new(key, client_id.encode(), hashlib.sha256).digest()
    return urlsafe_b64encode(digest).rstrip(b'=').decode()


def register_client(redirect_uris, client_name):
    """Mint a self-describing client_id; its secret is derived from it."""
    payload = {'redirect_uris': redirect_uris, 'name': client_name, 'iat': int(time.time())}
    client_id = _serializer('mcp-oauth-client').dumps(payload)
    return {
        'client_id': client_id,
        'client_secret': derive_client_secret(client_id),
        'redirect_uris': redirect_uris,
    }


def load_client(client_id):
    """Resolve a client_id to its registration, or None if it isn't ours."""
    static = static_client()
    if static and hmac.compare_digest(client_id, static['client_id']):
        return static
    try:
        payload = _serializer('mcp-oauth-client').loads(client_id)
    except BadSignature:
        return None
    return {
        'client_id': client_id,
        'client_secret': derive_client_secret(client_id),
        'redirect_uris': payload.get('redirect_uris') or [],
    }


def client_secret_matches(client, presented):
    expected = client.get('client_secret')
    if not expected:
        # A public client registered without a secret: PKCE is the protection.
        return True
    return bool(presented) and hmac.compare_digest(expected, presented)


def redirect_uri_allowed(client, redirect_uri):
    return redirect_uri in (client.get('redirect_uris') or [])


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------

def issue_access_token(user_id, client_id):
    return _serializer('mcp-oauth-access').dumps(
        {'user_id': user_id, 'client_id': client_id, 'scope': READ_SCOPE, 'type': 'access'})


def issue_refresh_token(user_id, client_id):
    return _serializer('mcp-oauth-refresh').dumps(
        {'user_id': user_id, 'client_id': client_id, 'scope': READ_SCOPE, 'type': 'refresh'})


def verify_access_token(token):
    """Return the token's claims, or None if invalid or expired."""
    try:
        payload = _serializer('mcp-oauth-access').loads(token, max_age=ACCESS_TOKEN_TTL)
    except (BadSignature, SignatureExpired):
        return None
    if payload.get('type') != 'access' or payload.get('scope') != READ_SCOPE:
        return None
    return payload


def verify_refresh_token(token):
    try:
        payload = _serializer('mcp-oauth-refresh').loads(token, max_age=REFRESH_TOKEN_TTL)
    except (BadSignature, SignatureExpired):
        return None
    return payload if payload.get('type') == 'refresh' else None


def issue_authorization_code(user_id, client_id, redirect_uri, code_challenge):
    return _serializer('mcp-oauth-code').dumps({
        'user_id': user_id,
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'code_challenge': code_challenge,
        'nonce': secrets.token_urlsafe(8),
    })


def consume_authorization_code(code):
    try:
        payload = _serializer('mcp-oauth-code').loads(code, max_age=AUTH_CODE_TTL)
    except (BadSignature, SignatureExpired):
        return None
    if code in _used_codes:
        return None
    _used_codes.add(code)
    if len(_used_codes) > 1000:
        _used_codes.clear()
    return payload


def pkce_matches(code_challenge, code_verifier):
    if not code_challenge:
        return False
    digest = hashlib.sha256(code_verifier.encode('ascii')).digest()
    expected = urlsafe_b64encode(digest).rstrip(b'=').decode()
    return hmac.compare_digest(expected, code_challenge)


# --------------------------------------------------------------------------
# Discovery metadata
# --------------------------------------------------------------------------

def _protected_resource_metadata():
    base = config.public_base_url(request)
    return jsonify({
        'resource': f'{base}/mcp',
        'authorization_servers': [base],
        'scopes_supported': [READ_SCOPE],
        'bearer_methods_supported': ['header'],
        'resource_documentation': f'{base}/',
    })


def _authorization_server_metadata():
    base = config.public_base_url(request)
    metadata = {
        'issuer': base,
        'authorization_endpoint': f'{base}/oauth/authorize',
        'token_endpoint': f'{base}/oauth/token',
        'scopes_supported': [READ_SCOPE],
        'response_types_supported': ['code'],
        'grant_types_supported': ['authorization_code', 'refresh_token'],
        'code_challenge_methods_supported': ['S256'],
        'token_endpoint_auth_methods_supported': [
            'client_secret_post', 'client_secret_basic', 'none',
        ],
    }
    if config.dynamic_registration_enabled():
        metadata['registration_endpoint'] = f'{base}/oauth/register'
    return jsonify(metadata)


# Clients probe both the bare path and the path with the resource appended.
oauth_bp.add_url_rule('/.well-known/oauth-protected-resource',
                      'protected_resource_metadata', _protected_resource_metadata)
oauth_bp.add_url_rule('/.well-known/oauth-protected-resource/mcp',
                      'protected_resource_metadata_mcp', _protected_resource_metadata)
oauth_bp.add_url_rule('/.well-known/oauth-authorization-server',
                      'authorization_server_metadata', _authorization_server_metadata)
oauth_bp.add_url_rule('/.well-known/oauth-authorization-server/mcp',
                      'authorization_server_metadata_mcp', _authorization_server_metadata)


# --------------------------------------------------------------------------
# Dynamic client registration
# --------------------------------------------------------------------------

@oauth_bp.route('/oauth/register', methods=['POST'])
def register():
    if not config.oauth_enabled() or not config.dynamic_registration_enabled():
        return jsonify({'error': 'access_denied',
                        'error_description': 'Dynamic client registration is disabled'}), 403

    body = request.get_json(silent=True) or {}
    redirect_uris = body.get('redirect_uris') or []
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return jsonify({'error': 'invalid_redirect_uri',
                        'error_description': 'redirect_uris is required'}), 400
    for uri in redirect_uris:
        parsed = urlparse(uri)
        if parsed.scheme != 'https' and parsed.hostname not in ('localhost', '127.0.0.1'):
            return jsonify({'error': 'invalid_redirect_uri',
                            'error_description': f'redirect_uri must use https: {uri}'}), 400

    client = register_client(redirect_uris, body.get('client_name', 'MCP client'))
    return jsonify({
        'client_id': client['client_id'],
        'client_secret': client['client_secret'],
        'client_id_issued_at': int(time.time()),
        'client_secret_expires_at': 0,   # never expires
        'redirect_uris': redirect_uris,
        'grant_types': ['authorization_code', 'refresh_token'],
        'response_types': ['code'],
        'token_endpoint_auth_method': 'client_secret_post',
        'scope': READ_SCOPE,
    }), 201


# --------------------------------------------------------------------------
# Authorization endpoint
# --------------------------------------------------------------------------

APPROVAL_PAGE = """
<!doctype html>
<title>Connect to Workout Log</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: -apple-system, system-ui, sans-serif; background:#111; color:#eee;
         display:flex; min-height:100vh; margin:0; align-items:center; justify-content:center; }
  .card { background:#1c1c1e; padding:28px; border-radius:14px; width:min(360px, 90vw); }
  h1 { font-size:19px; margin:0 0 6px; }
  p, ul { color:#9b9b9f; font-size:14px; line-height:1.5; }
  ul { padding-left:20px; }
  label { font-size:13px; color:#c7c7cc; }
  input { width:100%; box-sizing:border-box; padding:11px; margin:6px 0 14px;
          border-radius:8px; border:1px solid #3a3a3c; background:#2c2c2e; color:#fff; }
  button { width:100%; padding:12px; border:0; border-radius:8px; background:#0a84ff;
           color:#fff; font-size:15px; font-weight:600; }
  .err { color:#ff6b6b; }
</style>
<div class="card">
  <h1>Grant read-only access</h1>
  <p><strong>{{ client_name }}</strong> is asking to read:</p>
  <ul><li>Weight</li><li>Discipline</li><li>Nutrition</li><li>Personal records</li></ul>
  <p>It cannot add, change or delete anything.</p>
  {% if error %}<p class="err">{{ error }}</p>{% endif %}
  <form method="post">
    {% for key, value in params.items() %}
    <input type="hidden" name="{{ key }}" value="{{ value }}">
    {% endfor %}
    <label>Username</label>
    <input name="username" autocomplete="username" autofocus>
    <label>Password</label>
    <input name="password" type="password" autocomplete="current-password">
    <button type="submit">Approve read-only access</button>
  </form>
</div>
"""


def _authorize_error(redirect_uri, state, error, description):
    """Report back to the client once the redirect_uri is validated."""
    params = {'error': error, 'error_description': description}
    if state:
        params['state'] = state
    return redirect(f'{redirect_uri}?{urlencode(params)}')


@oauth_bp.route('/oauth/authorize', methods=['GET', 'POST'])
def authorize():
    if not config.oauth_enabled():
        return jsonify({'error': 'access_denied',
                        'error_description': 'This connector is disabled'}), 403

    source = request.form if request.method == 'POST' else request.args
    client_id = source.get('client_id', '')
    redirect_uri = source.get('redirect_uri', '')
    state = source.get('state', '')
    code_challenge = source.get('code_challenge', '')
    code_challenge_method = source.get('code_challenge_method', '')
    response_type = source.get('response_type', 'code')

    client = load_client(client_id) if client_id else None
    if client is None:
        return jsonify({'error': 'invalid_client',
                        'error_description': 'Unknown client_id'}), 400
    if not redirect_uri_allowed(client, redirect_uri):
        return jsonify({'error': 'invalid_request',
                        'error_description': 'redirect_uri is not registered for this client'}), 400

    if response_type != 'code':
        return _authorize_error(redirect_uri, state, 'unsupported_response_type',
                                'Only the authorization code flow is supported')
    if code_challenge_method != 'S256' or not code_challenge:
        return _authorize_error(redirect_uri, state, 'invalid_request',
                                'PKCE with code_challenge_method=S256 is required')

    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'state': state,
        'code_challenge': code_challenge,
        'code_challenge_method': code_challenge_method,
        'response_type': response_type,
        'scope': source.get('scope', READ_SCOPE),
    }

    if request.method == 'GET':
        return render_template_string(APPROVAL_PAGE, params=params, error=None,
                                      client_name='Claude')

    user = User.query.filter_by(username=source.get('username', '')).first()
    if not user or not check_password_hash(user.password, source.get('password', '')):
        page = render_template_string(APPROVAL_PAGE, params=params,
                                      error='Invalid username or password',
                                      client_name='Claude')
        response = make_response(page)
        response.status_code = 401
        return response

    result = {'code': issue_authorization_code(user.id, client_id, redirect_uri, code_challenge)}
    if state:
        result['state'] = state
    return redirect(f'{redirect_uri}?{urlencode(result)}')


# --------------------------------------------------------------------------
# Token endpoint
# --------------------------------------------------------------------------

def _client_credentials():
    """Read client credentials from the body, or from HTTP Basic auth."""
    client_id = request.form.get('client_id')
    client_secret = request.form.get('client_secret')
    if request.authorization and request.authorization.username:
        client_id = client_id or request.authorization.username
        client_secret = client_secret or request.authorization.password
    return client_id, client_secret


def _token_error(error, description, status=400):
    return jsonify({'error': error, 'error_description': description}), status


@oauth_bp.route('/oauth/token', methods=['POST'])
def token():
    if not config.oauth_enabled():
        return _token_error('invalid_client', 'This connector is disabled', 403)

    grant_type = request.form.get('grant_type')
    client_id, client_secret = _client_credentials()
    client = load_client(client_id) if client_id else None
    if client is None:
        return _token_error('invalid_client', 'Unknown client_id', 401)
    if not client_secret_matches(client, client_secret):
        return _token_error('invalid_client', 'Client authentication failed', 401)

    if grant_type == 'authorization_code':
        code = request.form.get('code', '')
        code_verifier = request.form.get('code_verifier', '')
        payload = consume_authorization_code(code) if code else None
        if payload is None:
            return _token_error('invalid_grant', 'Authorization code is invalid, expired or used')
        if payload['client_id'] != client_id:
            return _token_error('invalid_grant', 'Code was issued to a different client')
        if payload['redirect_uri'] != request.form.get('redirect_uri', payload['redirect_uri']):
            return _token_error('invalid_grant', 'redirect_uri does not match the request')
        if not code_verifier or not pkce_matches(payload['code_challenge'], code_verifier):
            return _token_error('invalid_grant', 'PKCE verification failed')
        user_id = payload['user_id']

    elif grant_type == 'refresh_token':
        payload = verify_refresh_token(request.form.get('refresh_token', ''))
        if payload is None:
            return _token_error('invalid_grant', 'Refresh token is invalid or expired')
        if payload['client_id'] != client_id:
            return _token_error('invalid_grant', 'Refresh token was issued to a different client')
        user_id = payload['user_id']

    else:
        return _token_error('unsupported_grant_type', 'Use authorization_code or refresh_token')

    if User.query.get(user_id) is None:
        return _token_error('invalid_grant', 'The account for this grant no longer exists')

    response = jsonify({
        'access_token': issue_access_token(user_id, client_id),
        'token_type': 'Bearer',
        'expires_in': ACCESS_TOKEN_TTL,
        'refresh_token': issue_refresh_token(user_id, client_id),
        'scope': READ_SCOPE,
    })
    response.headers['Cache-Control'] = 'no-store'
    return response
