"""Read-only mirror of the tables this connector reads.

This service deploys on its own (Railway root directory ``mcp/``) and therefore
cannot import the main app's ``models.py``. What lives here is a deliberately
narrow view: the same table and column names, but only the columns the four
exposed areas need, and no ``db.create_all()`` anywhere - this service never
creates or migrates a schema, it only reads one the main app owns.

If a column or table is ever renamed in the main app's models.py, mirror the
rename here.
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# Exercise categories, in the order the PRs page groups them by.
EXERCISE_TYPES = ['Pull', 'Push', 'Legs', 'Core', 'Cardio', 'Compound']


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)


class Exercise(db.Model):
    __tablename__ = 'exercises'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    exercise_type = db.Column(db.String(50))
    is_bodyweight = db.Column(db.Boolean, default=False, nullable=False)
    is_cardio = db.Column(db.Boolean, default=False, nullable=False)


class PersonalRecord(db.Model):
    __tablename__ = 'personal_records'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercises.id'), nullable=False, index=True)
    weight = db.Column(db.Float)
    reps = db.Column(db.Integer)
    calories = db.Column(db.Float)
    time_minutes = db.Column(db.Float)
    achieved_at = db.Column(db.DateTime)

    exercise = db.relationship('Exercise', lazy='joined')


class WeightLog(db.Model):
    __tablename__ = 'weight_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    weight = db.Column(db.Float, nullable=False)
    body_fat_percentage = db.Column(db.Float)
    visceral_fat = db.Column(db.Float)
    notes = db.Column(db.Text)
    logged_at = db.Column(db.DateTime, index=True)


class FoodPreset(db.Model):
    __tablename__ = 'food_presets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    protein_per_serving = db.Column(db.Float, nullable=False)
    serving_unit = db.Column(db.String(50))


class ProteinLog(db.Model):
    __tablename__ = 'protein_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    food_name = db.Column(db.String(100), nullable=False)
    protein_g = db.Column(db.Float, nullable=False)
    logged_at = db.Column(db.DateTime, index=True)
    preset_id = db.Column(db.Integer, db.ForeignKey('food_presets.id'))


class StreakLog(db.Model):
    __tablename__ = 'streak_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime)
    relapse_note = db.Column(db.Text)
