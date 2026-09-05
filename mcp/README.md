# Workout Log Connector (MCP)

A **standalone, read-only** service that exposes four areas of the workout app -
**weight**, **discipline**, **nutrition** and **PRs** - to Claude as a custom
connector, and to scripts as a plain REST API.

It deploys as its own Railway service pointing at this folder, next to the main
app, and reads the same Postgres database.

```
Postgres ──┬── Workout_Logging_App   (the app, read + write)
           └── Workout Log Connector (this folder, read only)
                     ▲
                     │ MCP over HTTPS + OAuth
                  Claude
```

## Why it is read-only

Not a convention - it is structural:

* no route accepts a write method (the REST endpoints are GET only, and the
  POSTs are the MCP JSON-RPC and OAuth endpoints);
* every collector in `data.py` issues SELECTs and nothing else;
* the tools are declared with `readOnlyHint`, and there is no tool that writes;
* `models.py` here is a narrow mirror with **no `create_all()`** - the schema
  belongs to the main app, and this service never creates or migrates it.

## Deploying on Railway

1. In the same Railway project: **New → GitHub Repo →** this repository.
2. **Settings → Root Directory:** `mcp` — that is what makes this its own
   service rather than a second copy of the app.
3. **Settings → Networking:** generate a domain.
4. **Variables:**

| Variable | Value |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (Railway reference to the same database) |
| `MCP_SECRET_KEY` | Any long random string. Signs the tokens this connector issues; rotating it revokes them all. Does not have to match the main app. |
| `ADMIN_USERNAME` | Same username as the main app - it selects whose data is exposed |
| `MCP_PUBLIC_URL` | Optional on Railway - it defaults to the domain Railway injects. Set it only for a custom domain, e.g. `https://connector.example.com` |
| `MCP_ALLOWED_HOSTS` | Optional on Railway - same default. The Railway domain is always accepted regardless. |

Optional:

| Variable | Default | What it does |
|---|---|---|
| `API_READ_TOKEN` | - | Static bearer token(s) for curl and Claude Code. Comma-separate to rotate. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `MCP_OAUTH_CLIENT_ID` / `MCP_OAUTH_CLIENT_SECRET` | - | A pre-shared OAuth client, if you would rather paste credentials into Claude than let it register itself |
| `MCP_OAUTH_REDIRECT_URIS` | Claude's callbacks | Comma-separated callbacks allowed for that pre-shared client |
| `MCP_ENABLED` | `1` | `0` turns the `/mcp` endpoint off |
| `MCP_OAUTH_ENABLED` | `1` | `0` turns the OAuth endpoints off |
| `MCP_OAUTH_ALLOW_DYNAMIC_REGISTRATION` | `1` | `0` requires the pre-shared client |
| `API_USER` | `ADMIN_USERNAME` | Which account the connector reads |

`ADMIN_PASSWORD` is **not** needed here: the approval page checks the password
hash already stored in the shared `users` table.

## Connecting Claude

1. Claude → **Settings → Connectors → Add custom connector**.
2. URL: `https://your-connector.up.railway.app/mcp`
3. Leave the OAuth client ID/secret blank - Claude registers itself. (Fill them
   in only if you set `MCP_OAUTH_CLIENT_ID` / `MCP_OAUTH_CLIENT_SECRET` first.)
4. **Connect** → a login page appears → your app username and password →
   **Approve**. Claude now holds a read-only token.

For Claude Code, the static token is simpler:

```bash
claude mcp add --transport http workout-log https://your-connector.up.railway.app/mcp \
  --header "Authorization: Bearer $API_READ_TOKEN"
```

## Tools

| Tool | Returns |
|---|---|
| `get_weight` | Weight / body fat / visceral fat history, and the change over the window |
| `get_discipline` | Current streak, best streak, total clean days, milestones, past attempts |
| `get_nutrition` | Today's protein entries vs target, per-day totals, 30-day average, presets |
| `get_personal_records` | Current PR per exercise grouped by type, with an estimated 1RM |

## REST

```bash
curl -H "Authorization: Bearer $API_READ_TOKEN" https://your-connector.up.railway.app/api/v1/ping
curl -H "Authorization: Bearer $API_READ_TOKEN" "https://your-connector.up.railway.app/api/v1/weight?limit=30"
curl -H "Authorization: Bearer $API_READ_TOKEN" "https://your-connector.up.railway.app/api/v1/discipline?limit=20"
curl -H "Authorization: Bearer $API_READ_TOKEN" "https://your-connector.up.railway.app/api/v1/nutrition?days=7"
curl -H "Authorization: Bearer $API_READ_TOKEN" "https://your-connector.up.railway.app/api/v1/prs?exercise=bench"
```

Unauthenticated helpers: `GET /` describes the service, and `GET /healthz`
reports the database connection plus the settings that decide whether the OAuth
handshake can work - open it first when Claude cannot connect:

```json
{
  "status": "ok",
  "database": "reachable",
  "public_base_url": "https://your-connector.up.railway.app",
  "request_host": "your-connector.up.railway.app",
  "public_url_matches_request": true,
  "allowed_hosts": ["your-connector.up.railway.app"],
  "oauth_enabled": true,
  "dynamic_registration": true
}
```

`public_url_matches_request: false` is the usual cause of "Couldn't register
with the sign-in service": every OAuth endpoint Claude is told to call is built
from `public_base_url`, so if it names a host that isn't this service, the
registration request never arrives. The response carries a `warning` field
saying exactly what to change.

## Files

| File | What it holds |
|---|---|
| `server.py` | App factory, Host allow-list, `/`, `/healthz`, `/whoami`. Gunicorn entrypoint. |
| `config.py` | Every environment variable, in one place |
| `models.py` | Narrow read-only mirror of the tables this reads |
| `data.py` | The `collect_*` read queries behind every tool and endpoint |
| `auth.py` | Bearer token resolution shared by both surfaces |
| `mcp_endpoint.py` | `POST /mcp` - JSON-RPC, tool definitions, dispatch |
| `oauth.py` | OAuth 2.1: discovery, registration, authorize, token |
| `rest_api.py` | `GET /api/v1/...` |
| `check_schema.py` | Dev check that the mirror still matches the main app's models |

## Local development

```bash
cd mcp
pip install -r requirements.txt
cp .env.example .env      # point DATABASE_URL at the main app's database
python server.py          # http://localhost:8000
```

If you rename a column in the main app's `models.py`, mirror it here and
confirm with:

```bash
python mcp/check_schema.py    # from the repo root
```
