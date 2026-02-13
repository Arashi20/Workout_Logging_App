import os
import csv
import json
from io import StringIO
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from dotenv import load_dotenv
from models import db, User, Exercise, WorkoutSession, WorkoutLog, PersonalRecord, WeightLog, BloodworkLog
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()

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
        current_year = datetime.utcnow().year
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
            PersonalRecord.user_id == current_user.id
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
    exercises_list = [{'id': ex.id, 'name': ex.name} for ex in exercises]
    workout_logs = []
    
    if active_session:
        workout_logs = WorkoutLog.query.filter_by(session_id=active_session.id).order_by(WorkoutLog.created_at).all()
    
    return render_template('workout.html', 
                         active_session=active_session,
                         exercises=exercises_list,
                         workout_logs=workout_logs)

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
            session = WorkoutSession(user_id=current_user.id, start_time=datetime.utcnow())
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
    
    # Add workout log
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
    
    # Update PR if applicable
    if set_type == 'working' and weight_float:
        update_pr(current_user.id, exercise.id, weight_float, reps_int)
    
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
        active_session.end_time = datetime.utcnow()
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

def update_pr(user_id, exercise_id, weight, reps):
    """Update personal record if the new weight is higher"""
    pr = PersonalRecord.query.filter_by(user_id=user_id, exercise_id=exercise_id).first()
    
    if not pr or weight > pr.weight:
        if pr:
            pr.weight = weight
            pr.reps = reps
            pr.achieved_at = datetime.utcnow()
        else:
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
    personal_records = PersonalRecord.query.filter_by(user_id=current_user.id).order_by(PersonalRecord.achieved_at.desc()).all()
    return render_template('prs.html', prs=personal_records)

@app.route('/weight-tracker')
@login_required
def weight_tracker():
    weight_logs = WeightLog.query.filter_by(user_id=current_user.id).order_by(WeightLog.logged_at.desc()).all()
    return render_template('weight_tracker.html', weight_logs=weight_logs, now=datetime.utcnow())

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
        # Use current UTC time when no date is provided
        logged_at = datetime.utcnow()
    
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
    all_exercises = Exercise.query.order_by(Exercise.exercise_type, Exercise.name).all()
    
    # Group exercises by type
    grouped_exercises = {}
    exercise_types_order = ['Pull', 'Push', 'Legs', 'Core', 'Cardio']
    
    for exercise in all_exercises:
        ex_type = exercise.exercise_type or 'Uncategorized'
        if ex_type not in grouped_exercises:
            grouped_exercises[ex_type] = []
        grouped_exercises[ex_type].append(exercise)
    
    # Sort the groups to show in the order: Pull, Push, Legs, Core, Cardio, then others
    sorted_groups = []
    for ex_type in exercise_types_order:
        if ex_type in grouped_exercises:
            sorted_groups.append((ex_type, grouped_exercises[ex_type]))
    
    # Add any remaining types (Uncategorized or old types)
    for ex_type, exercises_list in grouped_exercises.items():
        if ex_type not in exercise_types_order:
            sorted_groups.append((ex_type, exercises_list))
    
    return render_template('exercises.html', grouped_exercises=sorted_groups)

@app.route('/exercises/add', methods=['POST'])
@login_required
def add_exercise():
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    exercise_type = request.form.get('exercise_type', '').strip()
    
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
        exercise_type=exercise_type or None
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
        test_date = datetime.strptime(test_date_str, '%Y-%m-%d') if test_date_str else datetime.utcnow()
        
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
        'exercise_name', 'set_number', 'reps', 'weight', 'set_type'
    ])
    
    # Write data rows
    for log in logs:
        writer.writerow([
            log.session_id,
            log.session_date.strftime('%Y-%m-%d %H:%M:%S') if log.session_date else '',
            log.duration_minutes if log.duration_minutes else '',
            log.exercise_name,
            log.set_number,
            log.reps,
            log.weight if log.weight else '',
            log.set_type
        ])
    
    # Prepare response
    output = si.getvalue()
    si.close()
    
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=workout_logs_{datetime.utcnow().strftime("%Y%m%d")}.csv'}
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
        headers={'Content-Disposition': f'attachment; filename=weight_logs_{datetime.utcnow().strftime("%Y%m%d")}.csv'}
    )

@app.route('/export/personal-records')
@login_required
def export_personal_records():
    """Export personal records as CSV"""
    prs = db.session.query(
        Exercise.name.label('exercise_name'),
        PersonalRecord.weight,
        PersonalRecord.reps,
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
    writer.writerow(['exercise_name', 'weight', 'reps', 'achieved_date'])
    
    # Write data rows
    for pr in prs:
        writer.writerow([
            pr.exercise_name,
            pr.weight,
            pr.reps,
            pr.achieved_at.strftime('%Y-%m-%d %H:%M:%S')
        ])
    
    # Prepare response
    output = si.getvalue()
    si.close()
    
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=personal_records_{datetime.utcnow().strftime("%Y%m%d")}.csv'}
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
        headers={'Content-Disposition': f'attachment; filename=bloodwork_logs_{datetime.utcnow().strftime("%Y%m%d")}.csv'}
    )


#When running the app in development mode run the following commands 
#In your terminal:
# flask init-db
# flask create-admin

@app.cli.command()
def init_db():
    """Initialize the database."""
    db.create_all()
    print('Database initialized.')

@app.cli.command()
def create_admin():
    """Create admin user."""
    username = os.getenv('ADMIN_USERNAME', 'admin')
    password = os.getenv('ADMIN_PASSWORD', 'admin123')
    
    user = User.query.filter_by(username=username).first()
    if user:
        print(f'User {username} already exists.')
        return
    
    user = User(username=username, password=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    print(f'Admin user created: {username}')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # Only enable debug mode if explicitly set via environment variable
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode)
