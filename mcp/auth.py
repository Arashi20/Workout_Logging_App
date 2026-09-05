"""Bearer token authentication shared by the REST and MCP surfaces."""

import hmac
from functools import wraps

from flask import jsonify, request

import config
from models import User


def bearer_token():
    """Pull the token out of the Authorization header, or out of X-API-Key."""
    header = request.headers.get('Authorization', '')
    if header.lower().startswith('bearer '):
        return header[7:].strip()
    return request.headers.get('X-API-Key', '').strip()


def check_static_token(token):
    """Compare against the configured static tokens in constant time."""
    return any(hmac.compare_digest(token, valid) for valid in config.api_tokens())


def api_user():
    """The account whose data this connector exposes.

    Single-user app: a valid token maps to the configured account rather than
    to a per-caller identity.
    """
    user = User.query.filter_by(username=config.api_username()).first()
    if user is None:
        # Fall back to the only account, so a renamed admin doesn't break this.
        user = User.query.order_by(User.id).first()
    return user


def resolve_token(token):
    """Return the user a token belongs to, or None."""
    if not token:
        return None

    if check_static_token(token):
        return api_user()

    if config.oauth_enabled():
        from oauth import verify_access_token

        claims = verify_access_token(token)
        if claims is not None:
            return User.query.get(claims['user_id'])

    return None


def challenge(message, status=401):
    """401 pointing the client at our OAuth metadata (RFC 9728)."""
    response = jsonify({'error': 'unauthorized', 'message': message})
    response.status_code = status
    metadata = f'{config.public_base_url(request)}/.well-known/oauth-protected-resource'
    response.headers['WWW-Authenticate'] = (
        f'Bearer realm="workout-log", resource_metadata="{metadata}"'
    )
    return response


def authenticate():
    """Return ``(user, None)`` on success or ``(None, response)`` on failure."""
    if not config.api_tokens() and not config.oauth_enabled():
        response = jsonify({
            'error': 'not_configured',
            'message': 'Set API_READ_TOKEN, or enable OAuth, to use this connector.',
        })
        response.status_code = 503
        return None, response

    token = bearer_token()
    if not token:
        return None, challenge('Missing bearer token')

    user = resolve_token(token)
    if user is None:
        return None, challenge('Invalid or expired token')
    return user, None


def token_required(view):
    """Wrap a view so it receives the authenticated user as its first argument."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        user, error = authenticate()
        if error is not None:
            return error
        return view(user, *args, **kwargs)

    return wrapper
