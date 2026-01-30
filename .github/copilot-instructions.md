# Copilot instructions for Workout_Logging_App

## Project overview
- Flask monolith with server-rendered HTML. Route handlers live in [app.py](app.py) and render templates under [templates/](templates/).
- Data model is in [models.py](models.py) using Flask-SQLAlchemy; relationships are defined with backrefs and cascade deletes for user-owned data.
- Static assets are under [static/](static/) with CSS in [static/css/style.css](static/css/style.css).

## Key architecture and flows
- Authentication uses Flask-Login; `login_view` is `login` and `current_user` gates most routes (see [app.py](app.py)).
- Workout sessions are stateful: an “active session” is the row with `end_time=None` for the current user. Routes read/write that in `workout`, `start_workout`, `add_set`, `finish_workout`.
- Adding a set creates or reuses an `Exercise`, increments `WorkoutLog.set_number`, and may update PRs via `update_pr()` (see [app.py](app.py)).
- Weight tracker chart data comes from `/weight-tracker/data` JSON; templates likely fetch this and render Chart.js on the client.
- Database URL normalization: if `DATABASE_URL` starts with `postgres://`, it is rewritten to `postgresql://` on startup.

## Data model notes
- `PersonalRecord` enforces uniqueness per user+exercise via a unique constraint (see [models.py](models.py)).
- `WorkoutSession` and `WorkoutLog` are linked by `session_id`; logs are deleted with the session via cascade.

## Developer workflows
- Local setup and env vars are documented in [README.md](README.md); key vars: `DATABASE_URL`, `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`.
- Initialize DB and create admin user via Flask CLI commands:
  - `flask init-db`
  - `flask create-admin`
- Run the app with `python app.py` (debug mode only if `FLASK_DEBUG=true`).

## Project conventions
- Input validation is performed inline in route handlers with `flash()` errors and redirects back to the same view (see `add_set` and `add_weight_log` in [app.py](app.py)).
- Exercise names are normalized to title case before persistence.
- Use `datetime.utcnow()` for timestamps across models and PR updates.

## Integration points
- Chart rendering is front-end only; server exposes data via JSON at `/weight-tracker/data`.
- Deployment expects a Procfile and Railway-style environment variables (see [README.md](README.md)).
