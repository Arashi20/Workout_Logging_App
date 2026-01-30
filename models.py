from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    workout_sessions = db.relationship('WorkoutSession', backref='user', lazy=True, cascade='all, delete-orphan')
    prs = db.relationship('PersonalRecord', backref='user', lazy=True, cascade='all, delete-orphan')
    workout_programs = db.relationship('WorkoutProgram', backref='user', lazy=True, cascade='all, delete-orphan')
    weight_logs = db.relationship('WeightLog', backref='user', lazy=True, cascade='all, delete-orphan')

class Exercise(db.Model):
    __tablename__ = 'exercises'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    exercise_type = db.Column(db.String(50))  # e.g., 'Strength', 'Cardio', 'Flexibility'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    workout_logs = db.relationship('WorkoutLog', backref='exercise', lazy=True)
    prs = db.relationship('PersonalRecord', backref='exercise', lazy=True)

class WorkoutSession(db.Model):
    __tablename__ = 'workout_sessions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    end_time = db.Column(db.DateTime)
    duration_minutes = db.Column(db.Integer)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    workout_logs = db.relationship('WorkoutLog', backref='session', lazy=True, cascade='all, delete-orphan')

class WorkoutLog(db.Model):
    __tablename__ = 'workout_logs'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('workout_sessions.id'), nullable=False)
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercises.id'), nullable=False)
    set_number = db.Column(db.Integer, nullable=False)
    reps = db.Column(db.Integer, nullable=False)
    weight = db.Column(db.Float)
    set_type = db.Column(db.String(20), default='working')  # 'warmup' or 'working'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PersonalRecord(db.Model):
    __tablename__ = 'personal_records'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercises.id'), nullable=False)
    weight = db.Column(db.Float, nullable=False)
    reps = db.Column(db.Integer, nullable=False)
    achieved_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('user_id', 'exercise_id', name='unique_user_exercise_pr'),)

class WorkoutProgram(db.Model):
    __tablename__ = 'workout_programs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    program_type = db.Column(db.String(50))  # e.g., 'Upper/Lower', 'PPL', 'Full Body'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class WeightLog(db.Model):
    __tablename__ = 'weight_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    weight = db.Column(db.Float, nullable=False)
    body_fat_percentage = db.Column(db.Float)
    visceral_fat = db.Column(db.Float)
    logged_at = db.Column(db.DateTime, default=datetime.utcnow)
