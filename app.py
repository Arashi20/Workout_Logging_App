import os
import csv
import json
from io import StringIO
from pathlib import Path
from collections import defaultdict
from operator import attrgetter
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from dotenv import load_dotenv
from models import db, User, Exercise, WorkoutSession, WorkoutLog, PersonalRecord, WeightLog, BloodworkLog
from sqlalchemy import event, text, inspect, func
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
import click
import pytz

load_dotenv()

# Constants
EXERCISE_TYPES = ['Pull', 'Push', 'Legs', 'Core', 'Cardio', 'Compound']
AMSTERDAM_TZ = pytz.timezone('Europe/Amsterdam')

def now_amsterdam():
    """Get current datetime in Amsterdam timezone as naive datetime for database storage"""
    return datetime.now(AMSTERDAM_TZ).replace(tzinfo=None)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///workout.db')
# Normalize DATABASE_URL to use psycopg (version 3) driver
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql+psycopg://')
elif app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgresql://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgresql://', 'postgresql+psycopg://')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Database connection pool settings for better performance
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 5,           # Number of connections to maintain in the pool (reduced for Railway)
    'pool_recycle': 300,      # Recycle connections after 5 minutes (shorter for cloud DB)
    'pool_pre_ping': True,    # Verify connections before using them
    'max_overflow': 5,        # Maximum additional connections when pool_size is exceeded
    'pool_timeout': 10        # Timeout for getting a connection from the pool (seconds)
}
# Session timeout: 20 minutes of inactivity
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=20)

db.init_app(app)

# Set statement timeout for PostgreSQL connections to prevent hanging queries
@event.listens_for(Engine, "connect")
def set_postgres_statement_timeout(dbapi_connection, connection_record):
    """Set a 30-second statement timeout for all PostgreSQL queries.
    
    This applies to both psycopg2 and psycopg3 connections.
    """
    # Check if this is a PostgreSQL connection (works for both psycopg2 and psycopg3)
    module_name = dbapi_connection.__class__.__module__
    if 'psycopg' in module_name or 'pg8000' in module_name:
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("SET statement_timeout = '30s'")
            cursor.close()
        except Exception:
            # Catch all exceptions to ensure connection setup never fails
            # Log only the error type to avoid exposing sensitive details
            app.logger.debug(f'Could not set statement timeout on {module_name}')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Auto-initialize database and admin user on startup
def init_app():
    """Initialize database tables and create admin user if needed"""
    with app.app_context():
        # Create all tables if they don't exist
        db.create_all()
        
        # Create admin user if it doesn't exist
        username = os.getenv('ADMIN_USERNAME', 'admin')
        password = os.getenv('ADMIN_PASSWORD', 'admin123')
        
        user = User.query.filter_by(username=username).first()
        if not user:
            user = User(username=username, password=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            app.logger.info(f'Admin user created: {username}')
        else:
            app.logger.info(f'Admin user already exists: {username}')

# Run initialization
init_app()

@app.route('/')
def index():
    if current_user.is_authenticated:
        # Calculate fun statistics for the landing page
        stats = {}
        
        # 1. Most favorite workout of all time (exercise with most workout logs)
        favorite_all_time = db.session.query(
            Exercise.name,
            db.func.count(WorkoutLog.id).label('count')
        ).join(
            WorkoutLog, Exercise.id == WorkoutLog.exercise_id
        ).join(
            WorkoutSession, WorkoutLog.session_id == WorkoutSession.id
        ).filter(
            WorkoutSession.user_id == current_user.id
        ).group_by(
            Exercise.id, Exercise.name
        ).order_by(
            db.func.count(WorkoutLog.id).desc()
        ).first()
        
        stats['favorite_all_time'] = favorite_all_time.name if favorite_all_time else None
        stats['favorite_all_time_count'] = favorite_all_time.count if favorite_all_time else 0
        
        # 2. Most favorite workout of this year
        current_year = now_amsterdam().year
        year_start = datetime(current_year, 1, 1)
        
        favorite_this_year = db.session.query(
            Exercise.name,
            db.func.count(WorkoutLog.id).label('count')
        ).join(
            WorkoutLog, Exercise.id == WorkoutLog.exercise_id
        ).join(
            WorkoutSession, WorkoutLog.session_id == WorkoutSession.id
        ).filter(
            WorkoutSession.user_id == current_user.id,
            WorkoutSession.start_time >= year_start
        ).group_by(
            Exercise.id, Exercise.name
        ).order_by(
            db.func.count(WorkoutLog.id).desc()
        ).first()
        
        stats['favorite_this_year'] = favorite_this_year.name if favorite_this_year else None
        stats['favorite_this_year_count'] = favorite_this_year.count if favorite_this_year else 0
        
        # 3. Highest weight lifted + corresponding exercise (max PR)
        max_pr = db.session.query(
            Exercise.name,
            PersonalRecord.weight,
            PersonalRecord.reps
        ).join(
            Exercise, PersonalRecord.exercise_id == Exercise.id
        ).filter(
            PersonalRecord.user_id == current_user.id,
            Exercise.is_cardio.is_(False)
        ).order_by(
            PersonalRecord.weight.desc()
        ).first()
        
        stats['max_pr_exercise'] = max_pr.name if max_pr else None
        stats['max_pr_weight'] = max_pr.weight if max_pr else 0
        stats['max_pr_reps'] = max_pr.reps if max_pr else 0
        
        # 4. Average weight lifted in last workout (excluding warmup sets)
        last_session = WorkoutSession.query.filter_by(
            user_id=current_user.id
        ).filter(
            WorkoutSession.end_time.isnot(None)
        ).order_by(
            WorkoutSession.end_time.desc()
        ).first()
        
        if last_session:
            # Calculate total weight and total reps from working sets only
            last_workout_stats = db.session.query(
                db.func.sum(WorkoutLog.weight * WorkoutLog.reps).label('total_weight'),
                db.func.sum(WorkoutLog.reps).label('total_reps')
            ).filter(
                WorkoutLog.session_id == last_session.id,
                WorkoutLog.set_type == 'working',
                WorkoutLog.weight.isnot(None)
            ).first()
            
            if last_workout_stats and last_workout_stats.total_reps and last_workout_stats.total_reps > 0:
                stats['avg_weight_last_workout'] = round(last_workout_stats.total_weight / last_workout_stats.total_reps, 2)
            else:
                stats['avg_weight_last_workout'] = 0
        else:
            stats['avg_weight_last_workout'] = 0
        
        return render_template('landing.html', stats=stats)
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            session.permanent = True
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/workout')
@login_required
def workout():
    # Get or create active session
    active_session = WorkoutSession.query.filter_by(
        user_id=current_user.id,
        end_time=None
    ).first()
    
    exercises = Exercise.query.order_by(Exercise.name).all()
    # Convert Exercise objects to dictionaries for JSON serialization
    exercises_list = [{'id': ex.id, 'name': ex.name, 'is_bodyweight': ex.is_bodyweight, 'is_cardio': ex.is_cardio} for ex in exercises]
    workout_logs = []
    
    start_epoch_ms = None
    if active_session:
        workout_logs = WorkoutLog.query.filter_by(session_id=active_session.id).order_by(WorkoutLog.created_at).all()
        start_epoch_ms = int(AMSTERDAM_TZ.localize(active_session.start_time).timestamp() * 1000)

    # Build a dict of best existing PRs keyed by exercise_id for the PR indicator
    best_subq = db.session.query(
        func.max(PersonalRecord.id).label('best_id')
    ).filter(
        PersonalRecord.user_id == current_user.id
    ).group_by(PersonalRecord.exercise_id).subquery()

    best_prs = PersonalRecord.query.join(
        best_subq, PersonalRecord.id == best_subq.c.best_id
    ).all()

    pr_by_exercise = {}
    for pr in best_prs:
        pr_by_exercise[pr.exercise_id] = {
            'weight': float(pr.weight) if pr.weight is not None else None,
            'reps': pr.reps,
            'calories': float(pr.calories) if pr.calories is not None else None,
        }

    # Determine which sets in the current session are potential PRs.
    # A set is a PR if it beats the historical best AND is the best set so far
    # in this session for that exercise (mirroring finish_workout PR logic).
    pr_set_ids = set()
    if active_session and workout_logs:
        session_best = {}  # exercise_id -> {'weight', 'reps', 'calories'}
        for log in workout_logs:
            if log.set_type != 'working':
                continue
            ex_id = log.exercise_id
            existing_pr = pr_by_exercise.get(ex_id)
            session_pr = session_best.get(ex_id)
            is_pr = False

            if log.weight is not None:
                weight = float(log.weight)
                reps = log.reps or 0
                beats_existing = (
                    not existing_pr
                    or existing_pr['weight'] is None
                    or weight > existing_pr['weight']
                    or (weight == existing_pr['weight'] and reps > (existing_pr['reps'] or 0))
                )
                beats_session = (
                    not session_pr
                    or weight > session_pr['weight']
                    or (weight == session_pr['weight'] and reps > session_pr['reps'])
                )
                is_pr = beats_existing and beats_session
                if beats_session:
                    session_best[ex_id] = {'weight': weight, 'reps': reps, 'calories': None}

            elif log.calories is not None:
                calories = float(log.calories)
                beats_existing = (
                    not existing_pr
                    or existing_pr['calories'] is None
                    or calories > existing_pr['calories']
                )
                beats_session = (
                    not session_pr
                    or calories > session_pr['calories']
                )
                is_pr = beats_existing and beats_session
                if beats_session:
                    session_best[ex_id] = {'weight': None, 'reps': None, 'calories': calories}

            if is_pr:
                pr_set_ids.add(log.id)

    return render_template('workout.html',
                         active_session=active_session,
                         exercises=exercises_list,
                         workout_logs=workout_logs,
                         start_epoch_ms=start_epoch_ms,
                         pr_set_ids=pr_set_ids,
                         pr_by_exercise=pr_by_exercise)

@app.route('/workout/start', methods=['POST'])
@login_required
def start_workout():
    try:
        # Check if there's already an active session
        active_session = WorkoutSession.query.filter_by(
            user_id=current_user.id,
            end_time=None
        ).first()
        
        if not active_session:
            session = WorkoutSession(user_id=current_user.id, start_time=now_amsterdam())
            db.session.add(session)
            db.session.commit()
            flash('Workout session started!', 'success')
        
        return redirect(url_for('workout'))
    except SQLAlchemyError as e:
        db.session.rollback()
        # Log only the error type to avoid exposing sensitive database details
        app.logger.error(f'Database error starting workout session: {type(e).__name__}')
        flash('Unable to start workout session. Please try again.', 'danger')
        return redirect(url_for('workout'))

@app.route('/workout/add_set', methods=['POST'])
@login_required
def add_set():
    active_session = WorkoutSession.query.filter_by(
        user_id=current_user.id,
        end_time=None
    ).first()
    
    if not active_session:
        flash('Please start a workout session first', 'error')
        return redirect(url_for('workout'))
    
    exercise_id = request.form.get('exercise_id')
    reps = request.form.get('reps')
    weight = request.form.get('weight')
    set_type = request.form.get('set_type', 'working')
    
    # Validate set_type
    if set_type not in ['working', 'warmup']:
        flash('Invalid set type', 'error')
        return redirect(url_for('workout'))
    
    # Validate exercise_id
    if not exercise_id:
        flash('Please select an exercise', 'error')
        return redirect(url_for('workout'))
    
    try:
        exercise_id_int = int(exercise_id)
    except (ValueError, TypeError):
        flash('Invalid exercise selection', 'error')
        return redirect(url_for('workout'))
    
    # Get exercise
    exercise = Exercise.query.get(exercise_id_int)
    if not exercise:
        flash('Exercise not found', 'error')
        return redirect(url_for('workout'))
    
    # Handle cardio vs non-cardio exercises
    if exercise.is_cardio:
        # For cardio: weight = calories, reps = time_minutes
        calories_float = None
        if weight:
            try:
                calories_float = float(weight)
                if calories_float < 0 or calories_float > 10000:
                    flash('Calories must be between 0 and 10000', 'error')
                    return redirect(url_for('workout'))
            except (ValueError, TypeError):
                flash('Invalid calories value', 'error')
                return redirect(url_for('workout'))
        
        time_float = None
        if reps:
            try:
                time_float = float(reps)
                if time_float < 0.5 or time_float > 1000:
                    flash('Time must be between 0.5 and 1000 minutes', 'error')
                    return redirect(url_for('workout'))
            except (ValueError, TypeError):
                flash('Invalid time value', 'error')
                return redirect(url_for('workout'))
        
        if time_float is None:
            flash('Time is required for cardio exercises', 'error')
            return redirect(url_for('workout'))
        
        # Get the current set number for this exercise in this session
        last_set = WorkoutLog.query.filter_by(
            session_id=active_session.id,
            exercise_id=exercise.id
        ).order_by(WorkoutLog.set_number.desc()).first()
        
        set_number = (last_set.set_number + 1) if last_set else 1
        
        # Add workout log for cardio
        workout_log = WorkoutLog(
            session_id=active_session.id,
            exercise_id=exercise.id,
            set_number=set_number,
            calories=calories_float,
            time_minutes=time_float,
            set_type=set_type
        )
    else:
        # For non-cardio: regular weight and reps
        try:
            reps_int = int(reps)
            if reps_int < 1 or reps_int > 1000:
                flash('Reps must be between 1 and 1000', 'error')
                return redirect(url_for('workout'))
        except (ValueError, TypeError):
            flash('Invalid reps value', 'error')
            return redirect(url_for('workout'))
        
        weight_float = None
        if weight:
            try:
                weight_float = float(weight)
                if weight_float < 0 or weight_float > 10000:
                    flash('Weight must be between 0 and 10000 kg', 'error')
                    return redirect(url_for('workout'))
            except (ValueError, TypeError):
                flash('Invalid weight value', 'error')
                return redirect(url_for('workout'))
        
        # Get the current set number for this exercise in this session
        last_set = WorkoutLog.query.filter_by(
            session_id=active_session.id,
            exercise_id=exercise.id
        ).order_by(WorkoutLog.set_number.desc()).first()
        
        set_number = (last_set.set_number + 1) if last_set else 1
        
        # Add workout log for non-cardio
        workout_log = WorkoutLog(
            session_id=active_session.id,
            exercise_id=exercise.id,
            set_number=set_number,
            reps=reps_int,
            weight=weight_float,
            set_type=set_type
        )
    
    db.session.add(workout_log)
    db.session.commit()
    
    # Note: PRs are updated when the workout is finished, not during the session
    
    flash('Set added successfully!', 'success')
    return redirect(url_for('workout'))

@app.route('/workout/finish', methods=['POST'])
@login_required
def finish_workout():
    active_session = WorkoutSession.query.filter_by(
        user_id=current_user.id,
        end_time=None
    ).first()
    
    if active_session:
        # Get all workout logs for this session
        all_logs = WorkoutLog.query.filter_by(session_id=active_session.id).all()
        
        if not all_logs:
            # No sets were logged, treat as cancelled workout
            db.session.delete(active_session)
            db.session.commit()
            flash('No sets were logged: workout cancelled!', 'info')
        else:
            # Process working sets from this session and update PRs
            for log in all_logs:
                if log.set_type == 'working':
                    if log.weight is not None:
                        update_pr(current_user.id, log.exercise_id, weight=log.weight, reps=log.reps)
                    elif log.calories is not None:
                        update_pr(current_user.id, log.exercise_id, calories=log.calories, time_minutes=log.time_minutes)
            
            # Mark session as finished
            active_session.end_time = now_amsterdam()
            duration = (active_session.end_time - active_session.start_time).total_seconds() / 60
            active_session.duration_minutes = int(duration)
            db.session.commit()
            flash(f'Workout finished! Duration: {int(duration)} minutes', 'success')
    
    return redirect(url_for('workout'))

@app.route('/workout/cancel', methods=['POST'])
@login_required
def cancel_workout():
    active_session = WorkoutSession.query.filter_by(
        user_id=current_user.id,
        end_time=None
    ).first()
    
    if active_session:
        db.session.delete(active_session)
        db.session.commit()
        flash('Workout cancelled successfully. All logged exercises have been removed.', 'info')
    
    return redirect(url_for('workout'))

@app.route('/workout/delete_set/<int:log_id>', methods=['POST'])
@login_required
def delete_set(log_id):
    # Get the workout log entry
    workout_log = WorkoutLog.query.get_or_404(log_id)
    
    # Verify the log belongs to the current user's active session
    active_session = WorkoutSession.query.filter_by(
        user_id=current_user.id,
        end_time=None
    ).first()
    
    if not active_session or workout_log.session_id != active_session.id:
        flash('This set cannot be deleted because it does not belong to your active workout session', 'error')
        return redirect(url_for('workout'))
    
    # Delete the set
    db.session.delete(workout_log)
    db.session.commit()
    flash('Set deleted successfully', 'success')
    
    return redirect(url_for('workout'))

def update_pr(user_id, exercise_id, weight=None, reps=None, calories=None, time_minutes=None):
    """Add a new personal record if the new performance is better than the current best.

    For strength exercises: PR is the highest weight lifted; if weight equals the
    current best, more reps at that weight also counts as a new PR.
    For cardio exercises: PR is the most calories burned in a single set.

    Historical PR rows are preserved in the database; only a new row is inserted
    when performance improves.
    """
    if calories is not None:
        # Cardio PR: tracked by calories burned — find current best
        best = PersonalRecord.query.filter_by(
            user_id=user_id, exercise_id=exercise_id
        ).order_by(PersonalRecord.calories.desc()).first()

        if not best or best.calories is None or calories > best.calories:
            pr = PersonalRecord(
                user_id=user_id,
                exercise_id=exercise_id,
                calories=calories,
                time_minutes=time_minutes
            )
            db.session.add(pr)
            db.session.commit()
    elif weight is not None:
        # Strength PR: tracked by weight lifted, then reps — find current best
        best = PersonalRecord.query.filter_by(
            user_id=user_id, exercise_id=exercise_id
        ).order_by(PersonalRecord.weight.desc(), PersonalRecord.reps.desc()).first()

        is_better = (
            not best
            or best.weight is None
            or weight > best.weight
            or (weight == best.weight and reps is not None and best.reps is not None and reps > best.reps)
        )
        if is_better:
            pr = PersonalRecord(
                user_id=user_id,
                exercise_id=exercise_id,
                weight=weight,
                reps=reps
            )
            db.session.add(pr)
            db.session.commit()


@app.route('/prs')
@login_required
def prs():
    # Subquery: for each exercise, find the id of the best (most recently inserted) PR.
    # Since update_pr() only inserts a new row when performance strictly improves,
    # the row with the highest id per exercise is always the current best PR.
    best_subq = db.session.query(
        func.max(PersonalRecord.id).label('best_id')
    ).filter(
        PersonalRecord.user_id == current_user.id
    ).group_by(PersonalRecord.exercise_id).subquery()

    personal_records = PersonalRecord.query.join(
        best_subq, PersonalRecord.id == best_subq.c.best_id
    ).all()
    
    # Group PRs by exercise type
    grouped_prs = defaultdict(list)
    
    for pr in personal_records:
        ex_type = pr.exercise.exercise_type or 'Uncategorized'
        grouped_prs[ex_type].append(pr)
    
    # Sort the groups to show in the order: Pull, Push, Legs, Core, Cardio, then others
    sorted_groups = []
    for ex_type in EXERCISE_TYPES:
        if ex_type in grouped_prs:
            sorted_groups.append((ex_type, grouped_prs[ex_type]))
    
    # Add any remaining types (Uncategorized or old types)
    for ex_type, prs_list in grouped_prs.items():
        if ex_type not in EXERCISE_TYPES:
            sorted_groups.append((ex_type, prs_list))
    
    return render_template('prs.html', grouped_prs=sorted_groups)

@app.route('/history')
@login_required
def history():
    # Get filter parameter
    filter_date = request.args.get('date', None)
    show_all = request.args.get('show_all', 'false').lower() == 'true'
    
    # Base query for completed workout sessions
    base_query = WorkoutSession.query.filter_by(
        user_id=current_user.id
    ).filter(
        WorkoutSession.end_time.isnot(None)
    )
    
    # Get all sessions for date filter list
    all_sessions = base_query.order_by(WorkoutSession.start_time.desc()).all()
    
    # Extract the 5 most recent unique dates for filter buttons
    available_dates = []
    seen_dates = set()
    for session in all_sessions:
        if len(available_dates) >= 5:
            break
        date_str = session.start_time.strftime('%Y-%m-%d')
        if date_str not in seen_dates:
            available_dates.append({
                'date': date_str,
                'display': session.start_time.strftime('%B %d, %Y')
            })
            seen_dates.add(date_str)
    
    # Filter sessions based on parameters
    if filter_date:
        # Filter by specific date
        try:
            filter_datetime = datetime.strptime(filter_date, '%Y-%m-%d')
            sessions = [s for s in all_sessions if s.start_time.date() == filter_datetime.date()]
        except ValueError:
            flash('Invalid date format', 'error')
            sessions = all_sessions[:5]
    elif show_all:
        # Show all sessions
        sessions = all_sessions
    else:
        # Default: show last 5 sessions
        sessions = all_sessions[:5]
    
    # Calculate statistics for each session
    session_data = []
    for session in sessions:
        logs = sorted(session.workout_logs, key=lambda l: l.created_at)
        
        # Calculate total volume (weight x reps for all working sets)
        total_volume = sum(
            (log.weight or 0) * (log.reps or 0) 
            for log in logs 
            if log.set_type == 'working' and not log.exercise.is_cardio
        )
        
        # Count unique exercises
        unique_exercises = len(set(log.exercise.name for log in logs))
        
        # Count total sets (working sets only)
        total_sets = sum(1 for log in logs if log.set_type == 'working')
        
        # Get exercise breakdown
        exercise_breakdown = defaultdict(int)
        for log in logs:
            if log.set_type == 'working':
                exercise_breakdown[log.exercise.name] += 1
        
        session_data.append({
            'session': session,
            'total_volume': round(total_volume, 1),
            'unique_exercises': unique_exercises,
            'total_sets': total_sets,
            'exercise_breakdown': dict(exercise_breakdown)
        })
    
    return render_template('history.html', 
                          session_data=session_data,
                          available_dates=available_dates,
                          total_workouts=len(all_sessions),
                          showing_count=len(sessions),
                          filter_date=filter_date,
                          show_all=show_all)

@app.route('/weight-tracker')
@login_required
def weight_tracker():
    weight_logs = WeightLog.query.filter_by(user_id=current_user.id).order_by(WeightLog.logged_at.desc()).all()
    return render_template('weight_tracker.html', weight_logs=weight_logs, now=now_amsterdam())

@app.route('/weight-tracker/add', methods=['POST'])
@login_required
def add_weight_log():
    weight = request.form.get('weight')
    body_fat = request.form.get('body_fat_percentage')
    visceral_fat = request.form.get('visceral_fat')
    notes = request.form.get('notes', '').strip()
    log_date = request.form.get('log_date')
    
    # Validate and parse date
    # Note: All datetimes are stored as naive UTC datetimes for consistency
    if log_date:
        try:
            # Parse the date and treat it as UTC midnight
            logged_at = datetime.strptime(log_date, '%Y-%m-%d')
        except ValueError:
            flash('Invalid date format', 'error')
            return redirect(url_for('weight_tracker'))
    else:
        # Use current Amsterdam time when no date is provided
        logged_at = now_amsterdam()
    
    # Validate weight
    try:
        weight_float = float(weight)
        if weight_float <= 0 or weight_float > 500:
            flash('Weight must be between 0 and 500 kg', 'error')
            return redirect(url_for('weight_tracker'))
    except (ValueError, TypeError):
        flash('Invalid weight value', 'error')
        return redirect(url_for('weight_tracker'))
    
    # Validate body fat percentage
    body_fat_float = None
    if body_fat:
        try:
            body_fat_float = float(body_fat)
            if body_fat_float < 0 or body_fat_float > 100:
                flash('Body fat percentage must be between 0 and 100', 'error')
                return redirect(url_for('weight_tracker'))
        except (ValueError, TypeError):
            flash('Invalid body fat percentage value', 'error')
            return redirect(url_for('weight_tracker'))
    
    # Validate visceral fat
    visceral_fat_float = None
    if visceral_fat:
        try:
            visceral_fat_float = float(visceral_fat)
            if visceral_fat_float < 0 or visceral_fat_float > 100:
                flash('Visceral fat must be between 0 and 100', 'error')
                return redirect(url_for('weight_tracker'))
        except (ValueError, TypeError):
            flash('Invalid visceral fat value', 'error')
            return redirect(url_for('weight_tracker'))
    
    weight_log = WeightLog(
        user_id=current_user.id,
        weight=weight_float,
        body_fat_percentage=body_fat_float,
        visceral_fat=visceral_fat_float,
        notes=notes if notes else None,
        logged_at=logged_at
    )
    db.session.add(weight_log)
    db.session.commit()
    
    flash('Weight log added successfully!', 'success')
    return redirect(url_for('weight_tracker'))

@app.route('/weight-tracker/data')
@login_required
def weight_tracker_data():
    """API endpoint for weight tracker chart data"""
    weight_logs = WeightLog.query.filter_by(user_id=current_user.id).order_by(WeightLog.logged_at).all()
    
    data = {
        'dates': [log.logged_at.strftime('%Y-%m-%d') for log in weight_logs],
        'weights': [log.weight for log in weight_logs],
        'body_fat': [log.body_fat_percentage if log.body_fat_percentage else None for log in weight_logs],
        'visceral_fat': [log.visceral_fat if log.visceral_fat else None for log in weight_logs]
    }
    
    return jsonify(data)

@app.route('/exercises')
@login_required
def exercises():
    all_exercises = Exercise.query.all()
    
    # Group exercises by type
    grouped_exercises = defaultdict(list)
    
    for exercise in all_exercises:
        ex_type = exercise.exercise_type or 'Uncategorized'
        grouped_exercises[ex_type].append(exercise)
    
    # Sort exercises within each group alphabetically by name (case-insensitive)
    for ex_type in grouped_exercises:
        grouped_exercises[ex_type].sort(key=lambda e: e.name.lower())
    
    # Sort the groups to show in the order: Pull, Push, Legs, Core, Cardio, then others
    sorted_groups = []
    for ex_type in EXERCISE_TYPES:
        if ex_type in grouped_exercises:
            sorted_groups.append((ex_type, grouped_exercises[ex_type]))
    
    # Add any remaining types (Uncategorized or old types)
    for ex_type, exercises_list in grouped_exercises.items():
        if ex_type not in EXERCISE_TYPES:
            sorted_groups.append((ex_type, exercises_list))
    
    return render_template('exercises.html', grouped_exercises=sorted_groups, exercise_types=EXERCISE_TYPES)

@app.route('/exercises/add', methods=['POST'])
@login_required
def add_exercise():
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    exercise_type = request.form.get('exercise_type', '').strip()
    is_bodyweight = request.form.get('is_bodyweight') == 'on'
    is_cardio = request.form.get('is_cardio') == 'on'
    
    # Validate exercise name
    if not name or len(name) < 2:
        flash('Exercise name must be at least 2 characters', 'error')
        return redirect(url_for('exercises'))
    
    # Normalize name to title case
    name = name.title()
    
    # Check if exercise already exists
    existing_exercise = Exercise.query.filter_by(name=name).first()
    if existing_exercise:
        flash('Exercise already exists', 'error')
        return redirect(url_for('exercises'))
    
    exercise = Exercise(
        name=name,
        description=description or None,
        exercise_type=exercise_type or None,
        is_bodyweight=is_bodyweight,
        is_cardio=is_cardio
    )
    db.session.add(exercise)
    db.session.commit()
    
    flash('Exercise added successfully!', 'success')
    return redirect(url_for('exercises'))

@app.route('/exercises/delete/<int:exercise_id>', methods=['POST'])
@login_required
def delete_exercise(exercise_id):
    exercise = Exercise.query.get(exercise_id)
    if not exercise:
        flash('Exercise not found', 'error')
        return redirect(url_for('exercises'))
    
    try:
        # Delete associated PRs for all users
        PersonalRecord.query.filter_by(exercise_id=exercise.id).delete()
        
        # Delete associated workout logs for all users
        WorkoutLog.query.filter_by(exercise_id=exercise.id).delete()
        
        # Now delete the exercise
        db.session.delete(exercise)
        db.session.commit()
        flash('Exercise deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'Error deleting exercise {exercise_id}: {str(e)}')
        flash('Error deleting exercise', 'error')
    
    return redirect(url_for('exercises'))

def detect_plateau(session_data, min_sessions=4, window=6, improvement_threshold=0.025):
    """Detect if an exercise has plateaued based on estimated 1RM and volume progression.

    Args:
        session_data: list of dicts with 'date', 'max_1rm', 'total_volume', sorted by date
        min_sessions: minimum sessions required for analysis
        window: number of recent sessions to analyze
        improvement_threshold: minimum fractional improvement to be considered progressing (2.5%)

    Returns:
        dict with 'status' (progressing/stagnating/plateau/insufficient_data) and metrics
    """
    if len(session_data) < min_sessions:
        return {
            'status': 'insufficient_data',
            'sessions_analyzed': len(session_data),
            'strength_improvement_pct': None,
            'volume_improvement_pct': None,
            'early_max_1rm': None,
            'recent_max_1rm': None,
            'early_avg_volume': None,
            'recent_avg_volume': None,
        }

    recent = session_data[-window:]
    mid = len(recent) // 2
    early = recent[:mid]
    latest = recent[mid:]

    early_max_1rm = max(s['max_1rm'] for s in early)
    recent_max_1rm = max(s['max_1rm'] for s in latest)
    early_avg_volume = sum(s['total_volume'] for s in early) / len(early)
    recent_avg_volume = sum(s['total_volume'] for s in latest) / len(latest)

    strength_improvement = (recent_max_1rm - early_max_1rm) / early_max_1rm if early_max_1rm > 0 else 0
    volume_improvement = (recent_avg_volume - early_avg_volume) / early_avg_volume if early_avg_volume > 0 else 0

    strength_plateau = strength_improvement < improvement_threshold
    volume_plateau = volume_improvement < improvement_threshold

    if strength_plateau and volume_plateau:
        status = 'plateau'
    elif strength_plateau or volume_plateau:
        status = 'stagnating'
    else:
        status = 'progressing'

    return {
        'status': status,
        'sessions_analyzed': len(recent),
        'strength_improvement_pct': round(strength_improvement * 100, 1),
        'volume_improvement_pct': round(volume_improvement * 100, 1),
        'early_max_1rm': round(early_max_1rm, 1),
        'recent_max_1rm': round(recent_max_1rm, 1),
        'early_avg_volume': round(early_avg_volume, 1),
        'recent_avg_volume': round(recent_avg_volume, 1),
    }


def _build_session_data_for_exercise(exercise_id, user_id):
    """Return per-session aggregated data for plateau detection."""
    logs = db.session.query(WorkoutLog, WorkoutSession).join(
        WorkoutSession, WorkoutLog.session_id == WorkoutSession.id
    ).filter(
        WorkoutLog.exercise_id == exercise_id,
        WorkoutSession.user_id == user_id,
        WorkoutLog.set_type == 'working',
        WorkoutLog.weight.isnot(None),
        WorkoutLog.reps.isnot(None)
    ).order_by(WorkoutSession.start_time).all()

    session_data_dict = {}
    for log, session in logs:
        date = session.start_time.strftime('%Y-%m-%d')
        estimated_1rm = log.weight * (1 + log.reps / 30)
        volume = log.weight * log.reps
        if date not in session_data_dict:
            session_data_dict[date] = {'max_1rm': estimated_1rm, 'total_volume': volume}
        else:
            session_data_dict[date]['max_1rm'] = max(session_data_dict[date]['max_1rm'], estimated_1rm)
            session_data_dict[date]['total_volume'] += volume

    return [{'date': d, **v} for d, v in sorted(session_data_dict.items())]


@app.route('/plateaus')
@login_required
def plateaus():
    """Plateau detection dashboard showing analysis for all strength exercises."""
    exercises_with_data = db.session.query(Exercise).join(
        WorkoutLog, Exercise.id == WorkoutLog.exercise_id
    ).join(
        WorkoutSession, WorkoutLog.session_id == WorkoutSession.id
    ).filter(
        WorkoutSession.user_id == current_user.id,
        WorkoutLog.set_type == 'working',
        WorkoutLog.weight.isnot(None),
        WorkoutLog.reps.isnot(None)
    ).distinct().order_by(Exercise.name).all()

    exercise_analyses = []
    for exercise in exercises_with_data:
        session_data = _build_session_data_for_exercise(exercise.id, current_user.id)
        info = detect_plateau(session_data)
        info['exercise'] = exercise
        info['total_sessions'] = len(session_data)
        exercise_analyses.append(info)

    status_order = {'plateau': 0, 'stagnating': 1, 'progressing': 2, 'insufficient_data': 3}
    exercise_analyses.sort(key=lambda x: status_order.get(x['status'], 4))

    counts = {
        'plateau': sum(1 for a in exercise_analyses if a['status'] == 'plateau'),
        'stagnating': sum(1 for a in exercise_analyses if a['status'] == 'stagnating'),
        'progressing': sum(1 for a in exercise_analyses if a['status'] == 'progressing'),
        'insufficient_data': sum(1 for a in exercise_analyses if a['status'] == 'insufficient_data'),
    }

    return render_template('plateaus.html', exercise_analyses=exercise_analyses, counts=counts)


@app.route('/exercise/<int:exercise_id>')
@login_required
def exercise_detail(exercise_id):
    """Exercise detail page showing performance tracking and analytics"""
    exercise = Exercise.query.get_or_404(exercise_id)
    
    # Get all workout logs for this exercise by current user
    workout_logs = db.session.query(WorkoutLog, WorkoutSession).join(
        WorkoutSession, WorkoutLog.session_id == WorkoutSession.id
    ).filter(
        WorkoutLog.exercise_id == exercise_id,
        WorkoutSession.user_id == current_user.id,
        WorkoutLog.set_type == 'working'  # Only count working sets
    ).order_by(WorkoutSession.start_time).all()
    
    # Get current PR for this exercise
    current_pr = PersonalRecord.query.filter_by(
        user_id=current_user.id,
        exercise_id=exercise_id
    ).first()
    
    # Calculate performance metrics
    performance_data = []
    volume_data = []
    best_sets = {
        '1rm': None,
        '10rm': None
    }
    
    # Track dates seen to aggregate by session date
    session_dates = {}
    
    for log, session in workout_logs:
        session_date = session.start_time.strftime('%Y-%m-%d')
        
        if log.weight and log.reps:
            # Calculate estimated 1RM using Epley formula: weight * (1 + reps/30)
            estimated_1rm = round(log.weight * (1 + log.reps / 30), 1)
            volume = round(log.weight * log.reps, 1)
            
            # Track best max weight per session date for progression chart
            if session_date not in session_dates:
                session_dates[session_date] = {
                    'max_weight': round(log.weight, 1),
                    'total_volume': volume,
                    'estimated_1rm': estimated_1rm
                }
            else:
                session_dates[session_date]['max_weight'] = round(max(session_dates[session_date]['max_weight'], log.weight), 1)
                session_dates[session_date]['total_volume'] = round(session_dates[session_date]['total_volume'] + volume, 1)
                session_dates[session_date]['estimated_1rm'] = round(max(session_dates[session_date]['estimated_1rm'], estimated_1rm), 1)
            
            # Track best sets by different criteria
            if not best_sets['1rm'] or estimated_1rm > best_sets['1rm']['estimated_1rm']:
                best_sets['1rm'] = {
                    'weight': round(log.weight, 1),
                    'reps': log.reps,
                    'estimated_1rm': estimated_1rm,
                    'date': session.start_time
                }
            
            # Best 10-rep set
            if log.reps >= 10:
                if not best_sets['10rm'] or log.weight > best_sets['10rm']['weight']:
                    best_sets['10rm'] = {
                        'weight': round(log.weight, 1),
                        'reps': log.reps,
                        'date': session.start_time
                    }
    
    # Convert session data to sorted lists for charts
    sorted_dates = sorted(session_dates.keys())
    for date in sorted_dates:
        performance_data.append({
            'date': date,
            'weight': session_dates[date]['max_weight'],
            'estimated_1rm': session_dates[date]['estimated_1rm']
        })
        volume_data.append({
            'date': date,
            'volume': session_dates[date]['total_volume']
        })
    
    # Calculate total statistics
    total_sets = len(workout_logs)
    total_workouts = len(set(log[1].id for log in workout_logs))

    # Plateau detection for this exercise
    plateau_session_data = _build_session_data_for_exercise(exercise_id, current_user.id)
    plateau_info = detect_plateau(plateau_session_data)

    return render_template(
        'exercise_detail.html',
        exercise=exercise,
        performance_data=performance_data,
        volume_data=volume_data,
        best_sets=best_sets,
        current_pr=current_pr,
        total_sets=total_sets,
        total_workouts=total_workouts,
        plateau_info=plateau_info
    )

@app.route('/health')
@login_required
def health():
    """Health dashboard with genomics data and bloodwork"""
    # Load genomics insights
    insights_path = Path('public/insights.json')
    genomics_data = None
    
    if insights_path.exists():
        try:
            with open(insights_path, 'r') as f:
                genomics_data = json.load(f)
        except Exception as e:
            app.logger.error(f'Error loading genomics data: {str(e)}')
            flash('Error loading genomics data', 'error')
    
    # Fetch latest bloodwork results
    latest_bloodwork = BloodworkLog.query.filter_by(user_id=current_user.id).order_by(BloodworkLog.test_date.desc()).first()
    
    # Fetch all bloodwork results for history
    all_bloodwork = BloodworkLog.query.filter_by(user_id=current_user.id).order_by(BloodworkLog.test_date.desc()).all()
    
    return render_template('health.html', genomics=genomics_data, latest_bloodwork=latest_bloodwork, all_bloodwork=all_bloodwork)

@app.route('/health/bloodwork/add', methods=['POST'])
@login_required
def add_bloodwork():
    """Add new bloodwork results"""
    try:
        # Get form data
        test_date_str = request.form.get('test_date')
        test_date = datetime.strptime(test_date_str, '%Y-%m-%d') if test_date_str else now_amsterdam()
        
        # Create new bloodwork log
        bloodwork = BloodworkLog(
            user_id=current_user.id,
            test_date=test_date,
            notes=request.form.get('notes', '')
        )
        
        # Priority 1: Gym Bro Essentials
        if request.form.get('testosterone_total'):
            bloodwork.testosterone_total = float(request.form.get('testosterone_total'))
        if request.form.get('testosterone_free'):
            bloodwork.testosterone_free = float(request.form.get('testosterone_free'))
        if request.form.get('shbg'):
            bloodwork.shbg = float(request.form.get('shbg'))
        if request.form.get('oestradiol'):
            bloodwork.oestradiol = float(request.form.get('oestradiol'))
        if request.form.get('prolactin'):
            bloodwork.prolactin = float(request.form.get('prolactin'))
        
        # Priority 2: Metabolic Health
        if request.form.get('hba1c'):
            bloodwork.hba1c = float(request.form.get('hba1c'))
        if request.form.get('glucose_fasting'):
            bloodwork.glucose_fasting = float(request.form.get('glucose_fasting'))
        if request.form.get('insulin_fasting'):
            bloodwork.insulin_fasting = float(request.form.get('insulin_fasting'))
        if request.form.get('homa_index'):
            bloodwork.homa_index = float(request.form.get('homa_index'))
        
        db.session.add(bloodwork)
        db.session.commit()
        flash('Bloodwork results added successfully!', 'success')
    except ValueError as e:
        db.session.rollback()
        flash('Invalid input. Please enter valid numbers.', 'error')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'Error adding bloodwork: {str(e)}')
        flash('Error adding bloodwork results', 'error')
    
    return redirect(url_for('health'))

@app.route('/health/bloodwork/data')
@login_required
def bloodwork_chart_data():
    """Get bloodwork data formatted for chart (normalized percentages)"""
    latest = BloodworkLog.query.filter_by(user_id=current_user.id).order_by(BloodworkLog.test_date.desc()).first()
    
    if not latest:
        return jsonify({'labels': [], 'data': []})
    
    # Get all metrics with values
    labels = []
    data = []
    
    for field_name, ref_info in BloodworkLog.REFERENCE_RANGES.items():
        value = getattr(latest, field_name, None)
        if value is not None:
            percentage = latest.get_percentage_of_range(field_name)
            if percentage is not None:
                labels.append(ref_info['name'])
                data.append(percentage)
    
    return jsonify({
        'labels': labels,
        'data': data,
        'test_date': latest.test_date.strftime('%Y-%m-%d')
    })

# ---------------------------------------------------------------------------
# Workout Programs – pre-rendered, no database table required.
# To add a new program, append a dict to WORKOUT_PROGRAMS below.
# ---------------------------------------------------------------------------

WORKOUT_PROGRAMS = [
    {
        'id': 'heavy-duty-5day',
        'name': 'Heavy Duty 5-Day Split',
        'description': (
            'High-intensity 5-day split built around single working sets taken to '
            'failure. Each muscle group is trained twice per week across Upper and '
            'Lower days with two active rest days for neck & face work.'
        ),
        'note': (
            '1 lightweight warmup set before any of the sets '
            '(only if the targeted muscles have not been hit yet in that session).'
        ),
        'days': [
            {
                'label': 'Day 1: Upper',
                'avg_time': '30–45 min',
                'rest': False,
                'exercises': [
                    {'name': 'Seated Machine Row',          'prescription': '1× to failure'},
                    {'name': 'Incline Dumbbell Press',       'prescription': '1× to failure'},
                    {'name': 'Pec Deck',                     'prescription': '1× to failure'},
                    {'name': 'Lateral Raises',               'prescription': '1× dropset to failure'},
                    {'name': 'Uphill Treadmill',             'prescription': '5–10 min', 'optional': True},
                ],
            },
            {
                'label': 'Day 2: Lower + Core',
                'avg_time': '40–50 min',
                'rest': False,
                'exercises': [
                    {'name': 'Seated Leg Curl',                        'prescription': '1× to failure'},
                    {'name': 'Squat',                                   'prescription': '1× to failure'},
                    {'name': 'Leg Extension',                           'prescription': '1× to failure'},
                    {'name': 'Hip Abduction',                           'prescription': '1× to failure'},
                    {'name': 'Smith Machine Standing Calf Raises',      'prescription': '1× to failure'},
                    {'name': 'Machine Crunch',                          'prescription': '2× to failure'},
                ],
            },
            {
                'label': 'Day 3: Rest',
                'avg_time': '~30 min',
                'rest': True,
                'exercises': [
                    {'name': 'Neck + Face Exercises', 'prescription': ''},
                ],
            },
            {
                'label': 'Day 4: Upper + Core',
                'avg_time': '25–40 min',
                'rest': False,
                'exercises': [
                    {'name': '(Close-Grip) Lat Pulldown',   'prescription': '1× to failure'},
                    {'name': 'Dips',                         'prescription': '1× to failure'},
                    {'name': 'Seated Machine Shoulder Press','prescription': '1× to failure'},
                    {'name': 'Standing Barbell Curl',        'prescription': '1× to failure'},
                    {'name': 'Cable Tricep Pushdown',        'prescription': '1× to failure'},
                    {'name': 'Lying Leg Raises',             'prescription': '2× to failure'},
                ],
            },
            {
                'label': 'Day 5: Lower',
                'avg_time': '25–35 min',
                'rest': False,
                'exercises': [
                    {'name': 'Seated Leg Curl',                   'prescription': '1× to failure'},
                    {'name': 'Leg Extension (pre-exhaust) → Leg Press', 'prescription': '1× superset to failure'},
                    {'name': 'Back Extension',                    'prescription': '1× to failure'},
                    {'name': 'Hip Abduction',                     'prescription': '1× to failure'},
                    {'name': 'Uphill Treadmill',                  'prescription': '5–10 min', 'optional': True},
                ],
            },
            {
                'label': 'Day 6: Arms & Delts + Core',
                'avg_time': '40–45 min',
                'rest': False,
                'exercises': [
                    {'name': 'Hanging Leg Raises',                   'prescription': '2× to failure'},
                    {'name': 'Preacher Curl',                        'prescription': '1× to failure'},
                    {'name': 'EZ Bar Skull Crusher',                 'prescription': '1× to failure'},
                    {'name': 'Lateral Raises',                       'prescription': '1× dropset to failure'},
                    {'name': 'Reverse Pec Deck',                     'prescription': '1× to failure'},
                    {'name': 'Reverse Grip Barbell Wrist Curl',      'prescription': '1× dropset to failure'},
                ],
            },
            {
                'label': 'Day 7: Rest',
                'avg_time': '~30 min',
                'rest': True,
                'exercises': [
                    {'name': 'Neck + Face Exercises', 'prescription': ''},
                ],
            },
        ],
    },
]


@app.route('/programs')
@login_required
def programs():
    """Workout programs page – pre-rendered from WORKOUT_PROGRAMS, no DB needed."""
    return render_template('programs.html', programs=WORKOUT_PROGRAMS)


@app.route('/export/workout-logs')
@login_required
def export_workout_logs():
    """Export comprehensive workout log as CSV (denormalized - one row per set)"""
    # Query all workout logs for current user with related data
    logs = db.session.query(
        WorkoutSession.id.label('session_id'),
        WorkoutSession.start_time.label('session_date'),
        WorkoutSession.duration_minutes,
        Exercise.name.label('exercise_name'),
        WorkoutLog.set_number,
        WorkoutLog.reps,
        WorkoutLog.weight,
        WorkoutLog.calories,
        WorkoutLog.time_minutes,
        WorkoutLog.set_type
    ).join(
        WorkoutLog, WorkoutSession.id == WorkoutLog.session_id
    ).join(
        Exercise, WorkoutLog.exercise_id == Exercise.id
    ).filter(
        WorkoutSession.user_id == current_user.id
    ).order_by(
        WorkoutSession.start_time.desc(), WorkoutLog.id
    ).all()
    
    # Create CSV in memory
    si = StringIO()
    writer = csv.writer(si)
    
    # Write header
    writer.writerow([
        'session_id', 'session_date', 'session_duration_minutes', 
        'exercise_name', 'set_number', 'reps', 'weight', 'calories', 'time_minutes', 'set_type'
    ])
    
    # Write data rows
    for log in logs:
        writer.writerow([
            log.session_id,
            log.session_date.strftime('%Y-%m-%d %H:%M:%S') if log.session_date else '',
            log.duration_minutes if log.duration_minutes else '',
            log.exercise_name,
            log.set_number,
            log.reps if log.reps is not None else '',
            log.weight if log.weight is not None else '',
            log.calories if log.calories is not None else '',
            log.time_minutes if log.time_minutes is not None else '',
            log.set_type
        ])
    
    # Prepare response
    output = si.getvalue()
    si.close()
    
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=workout_logs_{now_amsterdam().strftime("%Y%m%d")}.csv'}
    )

@app.route('/export/weight-logs')
@login_required
def export_weight_logs():
    """Export weight tracker data as CSV"""
    weight_logs = WeightLog.query.filter_by(user_id=current_user.id).order_by(WeightLog.logged_at).all()
    
    # Create CSV in memory
    si = StringIO()
    writer = csv.writer(si)
    
    # Write header
    writer.writerow(['log_date', 'weight', 'body_fat_percentage', 'visceral_fat', 'notes'])
    
    # Write data rows
    for log in weight_logs:
        writer.writerow([
            log.logged_at.strftime('%Y-%m-%d %H:%M:%S'),
            log.weight,
            log.body_fat_percentage if log.body_fat_percentage else '',
            log.visceral_fat if log.visceral_fat else '',
            log.notes if log.notes else ''
        ])
    
    # Prepare response
    output = si.getvalue()
    si.close()
    
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=weight_logs_{now_amsterdam().strftime("%Y%m%d")}.csv'}
    )

@app.route('/export/personal-records')
@login_required
def export_personal_records():
    """Export personal records as CSV"""
    prs = db.session.query(
        Exercise.name.label('exercise_name'),
        PersonalRecord.weight,
        PersonalRecord.reps,
        PersonalRecord.calories,
        PersonalRecord.time_minutes,
        PersonalRecord.achieved_at
    ).join(
        Exercise, PersonalRecord.exercise_id == Exercise.id
    ).filter(
        PersonalRecord.user_id == current_user.id
    ).order_by(
        PersonalRecord.achieved_at.desc()
    ).all()
    
    # Create CSV in memory
    si = StringIO()
    writer = csv.writer(si)
    
    # Write header
    writer.writerow(['exercise_name', 'weight', 'reps', 'calories', 'time_minutes', 'achieved_date'])
    
    # Write data rows
    for pr in prs:
        writer.writerow([
            pr.exercise_name,
            pr.weight,
            pr.reps,
            pr.calories,
            pr.time_minutes,
            pr.achieved_at.strftime('%Y-%m-%d %H:%M:%S')
        ])
    
    # Prepare response
    output = si.getvalue()
    si.close()
    
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=personal_records_{now_amsterdam().strftime("%Y%m%d")}.csv'}
    )

@app.route('/export/bloodwork-logs')
@login_required
def export_bloodwork_logs():
    """Export bloodwork data as CSV"""
    bloodwork_logs = BloodworkLog.query.filter_by(user_id=current_user.id).order_by(BloodworkLog.test_date).all()
    
    # Create CSV in memory
    si = StringIO()
    writer = csv.writer(si)
    
    # Write header
    writer.writerow([
        'test_date', 'testosterone_total', 'testosterone_free', 'shbg', 
        'oestradiol', 'prolactin', 'hba1c', 'glucose_fasting', 
        'insulin_fasting', 'homa_index', 'notes'
    ])
    
    # Write data rows
    for log in bloodwork_logs:
        writer.writerow([
            log.test_date.strftime('%Y-%m-%d %H:%M:%S'),
            log.testosterone_total if log.testosterone_total else '',
            log.testosterone_free if log.testosterone_free else '',
            log.shbg if log.shbg else '',
            log.oestradiol if log.oestradiol else '',
            log.prolactin if log.prolactin else '',
            log.hba1c if log.hba1c else '',
            log.glucose_fasting if log.glucose_fasting else '',
            log.insulin_fasting if log.insulin_fasting else '',
            log.homa_index if log.homa_index else '',
            log.notes if log.notes else ''
        ])
    
    # Prepare response
    output = si.getvalue()
    si.close()
    
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=bloodwork_logs_{now_amsterdam().strftime("%Y%m%d")}.csv'}
    )


#When running the app in development mode run the following commands 
#In your terminal:
# flask init-db          # Initialize database tables (creates tables if they don't exist)
# flask create-admin     # Create admin user
# flask migrate-schema   # Run schema migrations to add missing columns (preserves data)
# flask reset-db         # Drop and recreate all tables (WARNING: deletes all data!)

def _create_admin_user():
    """Helper function to create admin user."""
    username = os.getenv('ADMIN_USERNAME', 'admin')
    password = os.getenv('ADMIN_PASSWORD', 'admin123')
    
    user = User(username=username, password=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    return username

@app.cli.command()
def init_db():
    """Initialize the database."""
    db.create_all()
    print('Database initialized.')

@app.cli.command()
def create_admin():
    """Create admin user."""
    username = os.getenv('ADMIN_USERNAME', 'admin')
    
    user = User.query.filter_by(username=username).first()
    if user:
        print(f'User {username} already exists.')
        return
    
    username = _create_admin_user()
    print(f'Admin user created: {username}')



@app.cli.command()
def reset_db():
    """Drop all tables and recreate them. WARNING: This will delete all data!"""
    print('WARNING: This will delete ALL data in the database!')
    print('This command should only be used in testing/development.')
    
    # Drop all tables
    db.drop_all()
    print('All tables dropped.')
    
    # Recreate all tables with current schema
    db.create_all()
    print('All tables recreated with current schema.')
    
    # Recreate admin user
    username = _create_admin_user()
    print(f'Admin user recreated: {username}')
    print('Database reset complete!')

    # Use the Railway pre-deploy input to run "flask reset-db" before deploying so that all tables are refreshed with the latest schema changes. This is especially useful during early development when the schema is changing frequently. Just be cautious when using this command as it will delete all existing data.

@app.cli.command()
def migrate_schema():
    """Run all necessary schema migrations to update the database."""
    print('Running schema migrations...')
    
    db_type = None  # Initialize for error handling
    
    try:
        # Determine database type
        db_type = db.engine.dialect.name
        
        # Get actual columns using raw SQL queries specific to each database type
        if db_type == 'sqlite':
            result = db.session.execute(text("PRAGMA table_info(exercises)")).fetchall()
            # PRAGMA table_info returns: (cid, name, type, notnull, dflt_value, pk)
            actual_columns = [row[1] for row in result]  # name is at index 1
        elif db_type == 'postgresql':
            result = db.session.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'exercises' ORDER BY ordinal_position"
            )).fetchall()
            actual_columns = [row[0] for row in result]
        else:
            # Fallback to inspector for other databases
            inspector = inspect(db.engine)
            if 'exercises' not in inspector.get_table_names():
                print('Exercises table does not exist. Creating all tables...')
                db.create_all()
                print('All tables created successfully.')
                return
            actual_columns = [col['name'] for col in inspector.get_columns('exercises')]
        
        print(f'Current columns in exercises table: {", ".join(actual_columns)}')
        
        # Add column(s) below if missing from the current schema
        # In Railway, just fill in "flask migrate-schema" as the command in the pre-deploy step and it will run this migration before deploying the new code with the updated model
        # Or add your migration script to \scripts and then use python \scripts\migrate_PLACEHOLDER to run it against your database URL directly for more complex migrations.

        
        
    except Exception as e:
        db.session.rollback()
        db_info = f' ({db_type})' if db_type else ''
        print(f'\n✗ Error during migration{db_info}: {e}')
        print('\nIf you continue to have issues, you may need to manually add the column')
        raise


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # Only enable debug mode if explicitly set via environment variable
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode)
