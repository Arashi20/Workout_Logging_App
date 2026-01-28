import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
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
    
    exercise_name = request.form.get('exercise_name')
    reps = request.form.get('reps')
    weight = request.form.get('weight')
    set_type = request.form.get('set_type', 'working')
    
    # Get or create exercise
    exercise = Exercise.query.filter_by(name=exercise_name).first()
    if not exercise:
        exercise = Exercise(name=exercise_name)
        db.session.add(exercise)
        db.session.commit()
    
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
        reps=int(reps),
        weight=float(weight) if weight else None,
        set_type=set_type
    )
    db.session.add(workout_log)
    db.session.commit()
    
    # Update PR if applicable
    if set_type == 'working' and weight:
        update_pr(current_user.id, exercise.id, float(weight), int(reps))
    
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
    name = request.form.get('name')
    description = request.form.get('description')
    program_type = request.form.get('program_type')
    
    program = WorkoutProgram(
        user_id=current_user.id,
        name=name,
        description=description,
        program_type=program_type
    )
    db.session.add(program)
    db.session.commit()
    
    flash('Program added successfully!', 'success')
    return redirect(url_for('programs'))

@app.route('/programs/delete/<int:program_id>', methods=['POST'])
@login_required
def delete_program(program_id):
    program = WorkoutProgram.query.get_or_404(program_id)
    if program.user_id == current_user.id:
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
    
    weight_log = WeightLog(
        user_id=current_user.id,
        weight=float(weight),
        body_fat_percentage=float(body_fat) if body_fat else None,
        visceral_fat=float(visceral_fat) if visceral_fat else None
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
    app.run(debug=True)
