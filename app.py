import os
import csv
from io import StringIO
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from dotenv import load_dotenv
from models import db, User, Exercise, WorkoutSession, WorkoutLog, PersonalRecord, WorkoutProgram, WeightLog

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///workout.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def index():
    if current_user.is_authenticated:
        return render_template('landing.html')
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
    workout_logs = []
    
    if active_session:
        workout_logs = WorkoutLog.query.filter_by(session_id=active_session.id).order_by(WorkoutLog.created_at).all()
    
    return render_template('workout.html', 
                         active_session=active_session,
                         exercises=exercises,
                         workout_logs=workout_logs)

@app.route('/workout/start', methods=['POST'])
@login_required
def start_workout():
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

@app.route('/programs')
@login_required
def programs():
    workout_programs = WorkoutProgram.query.filter_by(user_id=current_user.id).order_by(WorkoutProgram.created_at.desc()).all()
    return render_template('programs.html', programs=workout_programs)

@app.route('/programs/add', methods=['POST'])
@login_required
def add_program():
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    program_type = request.form.get('program_type')
    
    # Validate program name
    if not name or len(name) < 2:
        flash('Program name must be at least 2 characters', 'error')
        return redirect(url_for('programs'))
    
    program = WorkoutProgram(
        user_id=current_user.id,
        name=name,
        description=description if description else None,
        program_type=program_type
    )
    db.session.add(program)
    db.session.commit()
    
    flash('Program added successfully!', 'success')
    return redirect(url_for('programs'))

@app.route('/programs/delete/<int:program_id>', methods=['POST'])
@login_required
def delete_program(program_id):
    program = WorkoutProgram.query.filter_by(id=program_id, user_id=current_user.id).first()
    if not program:
        flash('Program not found or access denied', 'error')
        return redirect(url_for('programs'))
    
    db.session.delete(program)
    db.session.commit()
    flash('Program deleted successfully!', 'success')
    return redirect(url_for('programs'))

@app.route('/weight-tracker')
@login_required
def weight_tracker():
    weight_logs = WeightLog.query.filter_by(user_id=current_user.id).order_by(WeightLog.logged_at.desc()).all()
    return render_template('weight_tracker.html', weight_logs=weight_logs)

@app.route('/weight-tracker/add', methods=['POST'])
@login_required
def add_weight_log():
    weight = request.form.get('weight')
    body_fat = request.form.get('body_fat_percentage')
    visceral_fat = request.form.get('visceral_fat')
    notes = request.form.get('notes', '').strip()
    
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
        notes=notes if notes else None
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
    all_exercises = Exercise.query.order_by(Exercise.name).all()
    return render_template('exercises.html', exercises=all_exercises)

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
