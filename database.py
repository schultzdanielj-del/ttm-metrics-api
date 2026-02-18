"""
Database models and connection for TTM Metrics API
Uses PostgreSQL with SQLAlchemy ORM
"""

from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Boolean, Text, LargeBinary
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/ttm_metrics")
# Fix Railway Postgres URL (uses postgres:// instead of postgresql://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ============================================================================
# METRICS TABLES (Core fitness data)
# ============================================================================

class PR(Base):
    __tablename__ = "prs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    username = Column(String, nullable=False)
    exercise = Column(String, index=True, nullable=False)
    weight = Column(Float, nullable=False)
    reps = Column(Integer, nullable=False)
    estimated_1rm = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    message_id = Column(String, default="", nullable=False)
    channel_id = Column(String, default="", nullable=False)


class Workout(Base):
    __tablename__ = "workouts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    workout_letter = Column(String, nullable=False)
    exercise_order = Column(Integer, nullable=False)
    exercise_name = Column(String, nullable=False)
    setup_notes = Column(Text, nullable=True)
    video_link = Column(String, nullable=True)
    special_logging = Column(String, nullable=True)


class WorkoutCompletion(Base):
    __tablename__ = "workout_completions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    workout_letter = Column(String, nullable=False)
    completion_count = Column(Integer, default=0, nullable=False)
    last_workout_date = Column(DateTime, nullable=True)


class CoreFoodsLog(Base):
    __tablename__ = "core_foods_log"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    date = Column(String, nullable=False)
    completed = Column(Boolean, default=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)


# ============================================================================
# GAME TABLES (Gamification data)
# ============================================================================

class UserXP(Base):
    __tablename__ = "user_xp"
    user_id = Column(String, primary_key=True, index=True)
    username = Column(String, nullable=False)
    total_xp = Column(Integer, default=0, nullable=False)
    level = Column(Integer, default=1, nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow, nullable=False)


class WeeklyLog(Base):
    __tablename__ = "weekly_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    message_id = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    xp_awarded = Column(Integer, nullable=False)


class CoreFoodsCheckin(Base):
    __tablename__ = "core_foods_checkins"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    date = Column(String, nullable=False)
    message_id = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    xp_awarded = Column(Integer, nullable=False)
    protein_servings = Column(Integer, nullable=True)
    veggie_servings = Column(Integer, nullable=True)


# ============================================================================
# DASHBOARD TABLES
# ============================================================================

class DashboardMember(Base):
    __tablename__ = "dashboard_members"
    user_id = Column(String, primary_key=True, index=True)
    username = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    unique_code = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class UserNote(Base):
    """Per-exercise user notes from dashboard"""
    __tablename__ = "user_notes"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    exercise = Column(String, nullable=False)
    note = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ExerciseSwap(Base):
    """Exercise swaps per user per workout slot"""
    __tablename__ = "exercise_swaps"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    workout_letter = Column(String, nullable=False)
    exercise_index = Column(Integer, nullable=False)  # position in workout
    original_exercise = Column(String, nullable=False)
    swapped_exercise = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class WorkoutSession(Base):
    """96-hour session tracking per workout letter per user"""
    __tablename__ = "workout_sessions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    workout_letter = Column(String, nullable=False)
    opened_at = Column(DateTime, nullable=False)
    log_count = Column(Integer, default=0, nullable=False)


class CoachMessage(Base):
    """Two-way coach messaging between Dan and users"""
    __tablename__ = "coach_messages"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    message_text = Column(Text, nullable=True)
    audio_data = Column(LargeBinary, nullable=True)
    audio_duration = Column(Integer, nullable=True)
    from_coach = Column(Boolean, nullable=False)
    discord_msg_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ============================================================================
# Database initialization
# ============================================================================

def init_db():
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    print(f"Connecting to: {DATABASE_URL}")
    init_db()
