"""
Database models and connection for TTM Metrics API
Uses PostgreSQL with SQLAlchemy ORM
"""

from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Boolean, Text
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
    """Exercise PRs - logged from Discord bot or dashboard"""
    __tablename__ = "prs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    username = Column(String, nullable=False)
    exercise = Column(String, index=True, nullable=False)
    weight = Column(Float, nullable=False)
    reps = Column(Integer, nullable=False)
    estimated_1rm = Column(Float, nullable=False)  # Calculated: (weight * reps * 0.0333) + weight
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    message_id = Column(String, default="", nullable=False)  # Discord message ID or "dashboard"
    channel_id = Column(String, default="", nullable=False)  # Discord channel ID or "dashboard"


class Workout(Base):
    """Workout plans for dashboard users"""
    __tablename__ = "workouts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    workout_letter = Column(String, nullable=False)  # A, B, C, D, E
    exercise_order = Column(Integer, nullable=False)
    exercise_name = Column(String, nullable=False)
    setup_notes = Column(Text, nullable=True)
    video_link = Column(String, nullable=True)
    special_logging = Column(String, nullable=True)  # 'weight_only', 'reps_as_seconds', or None


class WorkoutCompletion(Base):
    """Tracks deload counter for each workout"""
    __tablename__ = "workout_completions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    workout_letter = Column(String, nullable=False)
    completion_count = Column(Integer, default=0, nullable=False)
    last_workout_date = Column(DateTime, nullable=True)


class CoreFoodsLog(Base):
    """Daily core foods check-ins"""
    __tablename__ = "core_foods_log"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    date = Column(String, nullable=False)  # YYYY-MM-DD format
    completed = Column(Boolean, default=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)


# ============================================================================
# GAME TABLES (Gamification data)
# ============================================================================

class UserXP(Base):
    """User XP and levels for gamification"""
    __tablename__ = "user_xp"
    
    user_id = Column(String, primary_key=True, index=True)
    username = Column(String, nullable=False)
    total_xp = Column(Integer, default=0, nullable=False)
    level = Column(Integer, default=1, nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow, nullable=False)


class WeeklyLog(Base):
    """Weekly training logs submitted by members"""
    __tablename__ = "weekly_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    message_id = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    xp_awarded = Column(Integer, nullable=False)


class CoreFoodsCheckin(Base):
    """Core foods check-ins from Discord (supports simple and learning modes)"""
    __tablename__ = "core_foods_checkins"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    date = Column(String, nullable=False)
    message_id = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    xp_awarded = Column(Integer, nullable=False)
    
    # Servings breakdown (optional - for "learning mode" in dashboard)
    # NULL = simple "core foods yes/no" mode
    # Values = learning mode with individual servings tracked
    protein_servings = Column(Integer, nullable=True)  # 0-4
    veggie_servings = Column(Integer, nullable=True)   # 0-3


# ============================================================================
# DASHBOARD TABLES (Dashboard-specific data)
# ============================================================================

class DashboardMember(Base):
    """Dashboard members with unique access codes"""
    __tablename__ = "dashboard_members"
    
    user_id = Column(String, primary_key=True, index=True)
    username = Column(String, nullable=False)
    unique_code = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ============================================================================
# Database initialization
# ============================================================================

def init_db():
    """Create all tables"""
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created successfully")


def get_db():
    """Dependency for FastAPI routes to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    # Test database connection
    print(f"Connecting to: {DATABASE_URL}")
    init_db()
