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
    weight_logs = db.relationship('WeightLog', backref='user', lazy=True, cascade='all, delete-orphan')
    bloodwork_logs = db.relationship('BloodworkLog', backref='user', lazy=True, cascade='all, delete-orphan')

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

class WeightLog(db.Model):
    __tablename__ = 'weight_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    weight = db.Column(db.Float, nullable=False)
    body_fat_percentage = db.Column(db.Float)
    visceral_fat = db.Column(db.Float)
    notes = db.Column(db.Text)
    logged_at = db.Column(db.DateTime, default=datetime.utcnow)

class BloodworkLog(db.Model):
    __tablename__ = 'bloodwork_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    test_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Priority 1: Gym Bro Essentials
    testosterone_total = db.Column(db.Float)  # nmol/l
    testosterone_free = db.Column(db.Float)   # pmol/l
    shbg = db.Column(db.Float)                # nmol/l
    oestradiol = db.Column(db.Float)          # pmol/l
    prolactin = db.Column(db.Float)           # mIU/l
    
    # Priority 2: Metabolic Health
    hba1c = db.Column(db.Float)               # %
    glucose_fasting = db.Column(db.Float)     # mmol/l
    insulin_fasting = db.Column(db.Float)     # mIU/l
    homa_index = db.Column(db.Float)          # calculated
    
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Define reference ranges as class attributes
    REFERENCE_RANGES = {
        'testosterone_total': {'min': 10.0, 'max': 35.0, 'unit': 'nmol/l', 'name': 'Testosterone Total'},
        'testosterone_free': {'min': 225.0, 'max': 725.0, 'unit': 'pmol/l', 'name': 'Testosterone Free'},
        'shbg': {'min': 18.0, 'max': 54.0, 'unit': 'nmol/l', 'name': 'SHBG'},
        'oestradiol': {'min': 40.0, 'max': 160.0, 'unit': 'pmol/l', 'name': 'Oestradiol'},
        'prolactin': {'min': 86.0, 'max': 324.0, 'unit': 'mIU/l', 'name': 'Prolactin'},
        'hba1c': {'min': 4.0, 'max': 5.6, 'unit': '%', 'name': 'HbA1c'},
        'glucose_fasting': {'min': 3.9, 'max': 5.5, 'unit': 'mmol/l', 'name': 'Glucose (Fasting)'},
        'insulin_fasting': {'min': 2.0, 'max': 25.0, 'unit': 'mIU/l', 'name': 'Insulin (Fasting)'},
        'homa_index': {'min': 0.0, 'max': 2.0, 'unit': '', 'name': 'HOMA-Index'}
    }
    
    def get_status(self, field_name):
        """Get status indicator (normal, high, low) for a given field"""
        value = getattr(self, field_name, None)
        if value is None:
            return None
        
        ref_range = self.REFERENCE_RANGES.get(field_name)
        if not ref_range:
            return None
            
        if value < ref_range['min']:
            return 'low'
        elif value > ref_range['max']:
            return 'high'
        else:
            return 'normal'
    
    def get_percentage_of_range(self, field_name):
        """Get value as percentage of reference range (for normalized chart)"""
        value = getattr(self, field_name, None)
        if value is None:
            return None
        
        ref_range = self.REFERENCE_RANGES.get(field_name)
        if not ref_range:
            return None
        
        # Calculate percentage: (value - min) / (max - min) * 100
        # This normalizes the value to 0-100% scale
        range_span = ref_range['max'] - ref_range['min']
        percentage = ((value - ref_range['min']) / range_span) * 100
        return round(percentage, 1)
