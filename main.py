"""
TTM Metrics API - FastAPI application
Handles all PR logging, workout tracking, and XP management
"""

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
import secrets

from database import get_db, init_db, PR, Workout, WorkoutCompletion, UserXP, DashboardMember, CoreFoodsLog as CoreFoodsLogModel
from schemas import (
    PRCreate, PRResponse, BestPRResponse,
    WorkoutPlanCreate, WorkoutCompletionUpdate, DeloadStatus,
    XPAward, XPResponse,
    DashboardMemberCreate, DashboardMemberResponse,
    CoreFoodsLog
)
from config import XP_REWARDS_API, XP_ENABLED

# Initialize FastAPI app
app = FastAPI(
    title="TTM Metrics API",
    description="Three Target Method - Fitness tracking and gamification API",
    version="1.0.0"
)

# CORS middleware (allow dashboard and Discord bot to access)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Startup
# ============================================================================

@app.on_event("startup")
def startup_event():
    """Initialize database on startup"""
    init_db()


# ============================================================================
# Health Check
# ============================================================================

@app.get("/")
def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "TTM Metrics API",
        "version": "1.0.0"
    }


# ============================================================================
# PR Endpoints
# ============================================================================

def calculate_1rm(weight: float, reps: int) -> float:
    """Calculate estimated 1RM using Epley formula"""
    if weight == 0:
        return reps  # For bodyweight, use reps as the metric
    return (weight * reps * 0.0333) + weight


@app.post("/api/prs", response_model=PRResponse, tags=["PRs"])
def log_pr(pr_data: PRCreate, db: Session = Depends(get_db)):
    """
    Log a new PR (Personal Record)
    
    - Calculates estimated 1RM
    - Checks if it's a new PR for this exercise
    - Returns PR info with is_new_pr flag
    - Bodyweight (weight=0) and weighted movements tracked separately
    """
    # Calculate 1RM
    estimated_1rm = calculate_1rm(pr_data.weight, pr_data.reps)
    
    # Check if this is a new PR - handle bodyweight vs weighted separately
    if pr_data.weight == 0:
        # For bodyweight: compare only against other bodyweight PRs (weight=0)
        best_pr = db.query(PR).filter(
            PR.user_id == pr_data.user_id,
            PR.exercise == pr_data.exercise,
            PR.weight == 0
        ).order_by(PR.estimated_1rm.desc()).first()
    else:
        # For weighted: compare only against other weighted PRs (weight>0)
        best_pr = db.query(PR).filter(
            PR.user_id == pr_data.user_id,
            PR.exercise == pr_data.exercise,
            PR.weight > 0
        ).order_by(PR.estimated_1rm.desc()).first()
    
    is_new_pr = not best_pr or estimated_1rm > best_pr.estimated_1rm
    
    # Create PR record
    new_pr = PR(
        user_id=pr_data.user_id,
        username=pr_data.username,
        exercise=pr_data.exercise,
        weight=pr_data.weight,
        reps=pr_data.reps,
        estimated_1rm=estimated_1rm,
        message_id=pr_data.message_id,
        channel_id=pr_data.channel_id,
        timestamp=datetime.utcnow()
    )
    
    db.add(new_pr)
    db.commit()
    db.refresh(new_pr)
    
    # Award XP if it's a new PR (only if XP system is enabled)
    if is_new_pr and XP_ENABLED:
        award_xp_internal(db, pr_data.user_id, pr_data.username, XP_REWARDS_API["pr"], "pr")
    
    response = PRResponse.from_orm(new_pr)
    response.is_new_pr = is_new_pr
    return response


@app.get("/api/prs/{user_id}", response_model=List[PRResponse], tags=["PRs"])
def get_user_prs(user_id: str, exercise: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db)):
    """
    Get PR history for a user
    
    - Optionally filter by exercise
    - Returns most recent first
    """
    query = db.query(PR).filter(PR.user_id == user_id)
    
    if exercise:
        query = query.filter(PR.exercise == exercise)
    
    prs = query.order_by(PR.timestamp.desc()).limit(limit).all()
    return [PRResponse.from_orm(pr) for pr in prs]
    
@app.get("/api/prs", response_model=List[PRResponse], tags=["PRs"])
def get_all_prs(limit: int = 1000, db: Session = Depends(get_db)):
    """
    Get all PRs across all users (for admin/cleanup purposes)
    
    - Returns most recent first
    - Default limit 1000
    """
    prs = db.query(PR).order_by(PR.recorded_at.desc()).limit(limit).all()
    return [PRResponse.from_orm(pr) for pr in prs]


@app.get("/api/prs/{user_id}/best/{exercise}", response_model=Optional[BestPRResponse], tags=["PRs"])
def get_best_pr(user_id: str, exercise: str, db: Session = Depends(get_db)):
    """
    Get best PR for a specific exercise
    
    - Returns the PR with highest estimated 1RM
    """
    best_pr = db.query(PR).filter(
        PR.user_id == user_id,
        PR.exercise == exercise
    ).order_by(PR.estimated_1rm.desc()).first()
    
    if not best_pr:
        return None

    
    return BestPRResponse.from_orm(best_pr)
    
@app.get("/api/prs", response_model=List[PRResponse], tags=["PRs"])
def get_all_prs(limit: int = 1000, db: Session = Depends(get_db)):
    """
    Get all PRs across all users (for admin/cleanup purposes)
    
    - Returns most recent first
    - Default limit 1000
    """
    prs = db.query(PR).order_by(PR.timestamp.desc()).limit(limit).all()
    return [PRResponse.from_orm(pr) for pr in prs]

@app.patch("/api/prs/batch", tags=["PRs"])
def batch_update_pr_exercises(updates: List[dict], db: Session = Depends(get_db)):
    """
    Batch update exercise names for PRs (for cleanup/canonicalization)
    
    Example request body:
    [
        {"pr_id": 123, "exercise": "incline ez bar tricep extension"},
        {"pr_id": 124, "exercise": "incline ez bar tricep extension"}
    ]
    """
    updated_count = 0
    
    for update in updates:
        pr_id = update.get("pr_id")
        new_exercise = update.get("exercise")
        
        if not pr_id or not new_exercise:
            continue
        
        pr = db.query(PR).filter(PR.id == pr_id).first()
        if pr:
            pr.exercise = new_exercise
            updated_count += 1
    
    db.commit()
    
    return {
        "updated_count": updated_count,
        "total_requested": len(updates)
    }

# ============================================================================
# Workout Plan Endpoints
# ============================================================================

@app.post("/api/workouts", tags=["Workouts"])
def create_workout_plan(plan: WorkoutPlanCreate, db: Session = Depends(get_db)):
    """
    Create or update a workout plan
    
    - Replaces existing plan for this workout letter
    """
    # Delete existing exercises for this workout
    db.query(Workout).filter(
        Workout.user_id == plan.user_id,
        Workout.workout_letter == plan.workout_letter
    ).delete()
    
    # Add new exercises
    for exercise in plan.exercises:
        workout = Workout(
            user_id=plan.user_id,
            workout_letter=plan.workout_letter,
            exercise_order=exercise.exercise_order,
            exercise_name=exercise.exercise_name,
            setup_notes=exercise.setup_notes,
            video_link=exercise.video_link,
            special_logging=exercise.special_logging
        )
        db.add(workout)
    
    # Initialize completion counter if doesn't exist
    completion = db.query(WorkoutCompletion).filter(
        WorkoutCompletion.user_id == plan.user_id,
        WorkoutCompletion.workout_letter == plan.workout_letter
    ).first()
    
    if not completion:
        completion = WorkoutCompletion(
            user_id=plan.user_id,
            workout_letter=plan.workout_letter,
            completion_count=0
        )
        db.add(completion)
    
    db.commit()
    return {"status": "success", "message": f"Workout {plan.workout_letter} created"}


@app.get("/api/workouts/{user_id}/{workout_letter}", tags=["Workouts"])
def get_workout_plan(user_id: str, workout_letter: str, db: Session = Depends(get_db)):
    """Get exercises for a specific workout"""
    exercises = db.query(Workout).filter(
        Workout.user_id == user_id,
        Workout.workout_letter == workout_letter
    ).order_by(Workout.exercise_order).all()
    
    return exercises


@app.post("/api/workouts/complete", tags=["Workouts"])
def complete_workout(completion: WorkoutCompletionUpdate, db: Session = Depends(get_db)):
    """
    Mark a workout as completed
    
    - Increments completion counter
    - Checks for 7-day gap and resets if needed
    - Awards 30 XP for completing workout
    - Returns updated deload status
    """
    # Get or create completion record
    record = db.query(WorkoutCompletion).filter(
        WorkoutCompletion.user_id == completion.user_id,
        WorkoutCompletion.workout_letter == completion.workout_letter
    ).first()
    
    if not record:
        record = WorkoutCompletion(
            user_id=completion.user_id,
            workout_letter=completion.workout_letter,
            completion_count=0
        )
        db.add(record)
    
    # Check if 7+ days since last workout across ALL workouts
    all_completions = db.query(WorkoutCompletion).filter(
        WorkoutCompletion.user_id == completion.user_id
    ).all()
    
    last_workout = max([c.last_workout_date for c in all_completions if c.last_workout_date], default=None)
    
    if last_workout:
        days_since = (datetime.utcnow() - last_workout).days
        if days_since >= 7:
            # Reset all counters
            for c in all_completions:
                c.completion_count = 0
    
    # Increment counter and update date
    record.completion_count += 1
    record.last_workout_date = datetime.utcnow()
    
    # Get username for XP award
    member = db.query(DashboardMember).filter(
        DashboardMember.user_id == completion.user_id
    ).first()
    
    username = member.username if member else "Unknown"
    
    # Award XP for completing workout (only if XP system is enabled)
    if XP_ENABLED:
        award_xp_internal(db, completion.user_id, username, XP_REWARDS_API["workout_complete"], "workout_complete")
    
    db.commit()
    db.refresh(record)
    
    return {
        "workout_letter": record.workout_letter,
        "completion_count": record.completion_count,
        "needs_deload": record.completion_count >= 6,
        "xp_awarded": XP_REWARDS_API["workout_complete"] if XP_ENABLED else 0
    }


@app.get("/api/workouts/{user_id}/deload-status", response_model=List[DeloadStatus], tags=["Workouts"])
def get_deload_status(user_id: str, db: Session = Depends(get_db)):
    """Get deload counter status for all workouts"""
    completions = db.query(WorkoutCompletion).filter(
        WorkoutCompletion.user_id == user_id
    ).all()
    
    return [
        DeloadStatus(
            workout_letter=c.workout_letter,
            completion_count=c.completion_count,
            needs_deload=c.completion_count >= 6
        )
        for c in completions
    ]


# ============================================================================
# XP Endpoints
# ============================================================================

def calculate_level(total_xp: int) -> int:
    """Calculate level based on total XP"""
    level = 1
    xp_needed = 500
    remaining_xp = total_xp
    
    while remaining_xp >= xp_needed:
        remaining_xp -= xp_needed
        level += 1
        xp_needed = 250 + (level * 250)
    
    return level


def xp_for_next_level(current_level: int) -> int:
    """Get XP needed for next level"""
    return 250 + (current_level * 250)


def award_xp_internal(db: Session, user_id: str, username: str, xp_amount: int, reason: str):
    """Internal function to award XP (used by other endpoints)"""
    user = db.query(UserXP).filter(UserXP.user_id == user_id).first()
    
    if not user:
        user = UserXP(
            user_id=user_id,
            username=username,
            total_xp=0,
            level=1
        )
        db.add(user)
    
    user.total_xp += xp_amount
    user.level = calculate_level(user.total_xp)
    user.last_updated = datetime.utcnow()
    
    db.commit()


@app.post("/api/xp/award", response_model=XPResponse, tags=["XP"])
def award_xp(xp_data: XPAward, db: Session = Depends(get_db)):
    """
    Award XP to a user
    
    - Automatically calculates level
    - Returns updated XP status
    - Only works if XP system is enabled
    """
    if not XP_ENABLED:
        raise HTTPException(status_code=400, detail="XP system is currently disabled")
    
    award_xp_internal(db, xp_data.user_id, xp_data.username, xp_data.xp_amount, xp_data.reason)
    
    user = db.query(UserXP).filter(UserXP.user_id == xp_data.user_id).first()
    
    return XPResponse(
        user_id=user.user_id,
        username=user.username,
        total_xp=user.total_xp,
        level=user.level,
        xp_for_next_level=xp_for_next_level(user.level)
    )


@app.get("/api/xp/{user_id}", response_model=XPResponse, tags=["XP"])
def get_user_xp(user_id: str, db: Session = Depends(get_db)):
    """Get user's current XP and level"""
    user = db.query(UserXP).filter(UserXP.user_id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return XPResponse(
        user_id=user.user_id,
        username=user.username,
        total_xp=user.total_xp,
        level=user.level,
        xp_for_next_level=xp_for_next_level(user.level)
    )


# ============================================================================
# Dashboard Member Endpoints
# ============================================================================

@app.post("/api/dashboard/members", response_model=DashboardMemberResponse, tags=["Dashboard"])
def create_dashboard_member(member: DashboardMemberCreate, db: Session = Depends(get_db)):
    """
    Create a dashboard member with unique access code
    
    - Generates unique access code
    - Returns dashboard URL
    """
    # Check if user already exists
    existing = db.query(DashboardMember).filter(
        DashboardMember.user_id == member.user_id
    ).first()
    
    if existing:
        return DashboardMemberResponse(
            user_id=existing.user_id,
            username=existing.username,
            unique_code=existing.unique_code,
            dashboard_url=f"https://your-dashboard-url.com/dashboard/{existing.unique_code}"
        )
    
    # Generate unique code
    unique_code = secrets.token_urlsafe(16)
    
    new_member = DashboardMember(
        user_id=member.user_id,
        username=member.username,
        unique_code=unique_code
    )
    
    db.add(new_member)
    db.commit()
    db.refresh(new_member)
    
    return DashboardMemberResponse(
        user_id=new_member.user_id,
        username=new_member.username,
        unique_code=new_member.unique_code,
        dashboard_url=f"https://your-dashboard-url.com/dashboard/{new_member.unique_code}"
    )


@app.get("/api/dashboard/members/{unique_code}", tags=["Dashboard"])
def get_dashboard_member(unique_code: str, db: Session = Depends(get_db)):
    """Get dashboard member by unique code"""
    member = db.query(DashboardMember).filter(
        DashboardMember.unique_code == unique_code
    ).first()
    
    if not member:
        raise HTTPException(status_code=404, detail="Invalid dashboard code")
    
    return member


# ============================================================================
# Core Foods Endpoints
# ============================================================================

@app.post("/api/core-foods", tags=["Core Foods"])
def log_core_foods(log: CoreFoodsLog, db: Session = Depends(get_db)):
    """Log core foods for a date"""
    # Check if already logged for this date
    existing = db.query(CoreFoodsLogModel).filter(
        CoreFoodsLogModel.user_id == log.user_id,
        CoreFoodsLogModel.date == log.date
    ).first()
    
    if existing:
        existing.completed = log.completed
        db.commit()
        return {"status": "updated", "message": "Core foods log updated"}
    
    new_log = CoreFoodsLogModel(
        user_id=log.user_id,
        date=log.date,
        completed=log.completed
    )
    
    db.add(new_log)
    db.commit()
    
    return {"status": "created", "message": "Core foods logged"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
