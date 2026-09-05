"""Standalone read-only connector for the Workout Logging App.

Deployed as its own Railway service pointing at this folder, sharing the main
app's Postgres database. It exposes four areas - weight, discipline, nutrition
and PRs - over MCP (for Claude custom connectors) and over plain REST, and it
never writes: no route accepts anything but GET or the MCP/OAuth POSTs, no
collector issues anything but SELECT, and the schema is owned entirely by the
main app.
"""

import os
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, jsonify, request

import config
from auth import authenticate
from mcp_endpoint import TOOLS, mcp_bp
from models import db
from oauth import oauth_bp
from rest_api import rest_api

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = config.secret_key()
    app.config['SQLALCHEMY_DATABASE_URI'] = config.database_url()
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 2,          # a connector serves one user; keep it small
        'pool_recycle': 300,
        'pool_pre_ping': True,
        'max_overflow': 2,
        'pool_timeout': 10,
    }

    # This service reads a schema the main app owns: no create_all, no migration.
    db.init_app(app)

    app.register_blueprint(rest_api)
    app.register_blueprint(mcp_bp)
    app.register_blueprint(oauth_bp)

    @app.before_request
    def enforce_allowed_hosts():
        """Reject requests carrying an unexpected Host header.

        An MCP server on a public URL should only answer to its own hostname,
        so a page that resolves someone else's name to this address cannot
        talk to it.
        """
        allowed = config.allowed_hosts()
        if not allowed:
            return None
        host = (request.host or '').split(':')[0]
        if host in allowed or host in ('localhost', '127.0.0.1'):
            return None
        return jsonify({'error': 'forbidden', 'message': 'Unexpected Host header'}), 403

    @app.route('/', methods=['GET'])
    def index():
        """What this service is, without giving anything away to an anonymous caller."""
        base = config.public_base_url(request)
        return jsonify({
            'service': 'workout-log-connector',
            'access': 'read-only',
            'areas': ['weight', 'discipline', 'nutrition', 'prs'],
            'mcp_endpoint': f'{base}/mcp',
            'tools': [tool['name'] for tool in TOOLS],
            'rest_endpoints': [f'{base}/api/v1/{name}' for name in
                               ('weight', 'discipline', 'nutrition', 'prs', 'ping')],
            'authorization_server': base,
        })

    @app.route('/healthz', methods=['GET'])
    def healthz():
        """Liveness probe, and the first place to look when Claude cannot connect.

        Reports the settings that decide whether the OAuth handshake can work -
        the base URL Claude is handed and the host this request arrived on -
        without exposing any secret.
        """
        base = config.public_base_url(request)
        report = {
            'status': 'ok',
            'public_base_url': base,
            'request_host': request.host,
            'public_url_matches_request': urlparse(base).hostname == request.host.split(':')[0],
            'allowed_hosts': config.allowed_hosts() or 'any',
            'oauth_enabled': config.oauth_enabled(),
            'dynamic_registration': config.dynamic_registration_enabled(),
        }
        warning = config.public_url_warning()
        if warning:
            report['warning'] = warning

        try:
            db.session.execute(db.text('SELECT 1'))
            report['database'] = 'reachable'
        except Exception:
            app.logger.exception('Health check could not reach the database')
            report['status'] = 'degraded'
            report['database'] = 'unreachable'
            return jsonify(report), 503

        return jsonify(report)

    @app.route('/whoami', methods=['GET'])
    def whoami():
        """Which account a token maps to - handy while setting the connector up."""
        user, error = authenticate()
        if error is not None:
            return error
        return jsonify({'user': user.username, 'scope': 'read'})

    warning = config.public_url_warning()
    if warning:
        app.logger.warning('Connector misconfiguration: %s', warning)

    return app


app = create_app()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8000)),
            debug=config.flag('FLASK_DEBUG', '0'))
