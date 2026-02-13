"""
TTM Metrics API - FastAPI application
Handles all PR logging, workout tracking, and XP management
"""

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, Optional
from datetime import datetime, timedelta
import secrets

from database import (
    get_db, init_db, PR, Workout, WorkoutCompletion, UserXP,
    DashboardMember, CoreFoodsLog as CoreFoodsLogModel, WeeklyLog,
    CoreFoodsCheckin, UserNote, ExerciseSwap, WorkoutSession
)
from schemas import (
    PRCreate, PRResponse, BestPRResponse,
    WorkoutPlanCreate, WorkoutCompletionUpdate, DeloadStatus,
    XPAward, XPResponse,
    DashboardMemberCreate, DashboardMemberResponse,
    CoreFoodsLog
)
from config import XP_REWARDS_API, XP_ENABLED

app = FastAPI(
    title="TTM Metrics API",
    description="Three Target Method - Fitness tracking and gamification API",
    version="1.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    init_db()


@app.get("/")
def root():
    return {"status": "healthy", "service": "TTM Metrics API", "version": "1.1.0"}


# ============================================================================
# Helpers
# ============================================================================

def calculate_1rm(weight: float, reps: int) -> float:
    if weight == 0:
        return reps
    return (weight * reps * 0.0333) + weight


def _resolve_member(unique_code: str, db: Session) -> DashboardMember:
    member = db.query(DashboardMember).filter(
        DashboardMember.unique_code == unique_code
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Not Found")
    return member


def _get_best_pr_for_exercise(db: Session, user_id: str, exercise: str):
    return db.query(PR).filter(
        PR.user_id == user_id,
        PR.exercise == exercise
    ).order_by(PR.estimated_1rm.desc()).first()


def _format_pr(pr) -> str:
    if not pr:
        return None
    if pr.weight == 0:
        return f"BW/{pr.reps}"
    w = int(pr.weight) if pr.weight == int(pr.weight) else pr.weight
    return f"{w}/{pr.reps}"


# ============================================================================
# PR Endpoints
# ============================================================================

@app.post("/api/prs", response_model=PRResponse, tags=["PRs"])
def log_pr(pr_data: PRCreate, db: Session = Depends(get_db)):
    estimated_1rm = calculate_1rm(pr_data.weight, pr_data.reps)
    if pr_data.weight == 0:
        best_pr = db.query(PR).filter(
            PR.user_id == pr_data.user_id,
            PR.exercise == pr_data.exercise,
            PR.weight == 0
        ).order_by(PR.estimated_1rm.desc()).first()
    else:
        best_pr = db.query(PR).filter(
            PR.user_id == pr_data.user_id,
            PR.exercise == pr_data.exercise,
            PR.weight > 0
        ).order_by(PR.estimated_1rm.desc()).first()
    is_new_pr = not best_pr or estimated_1rm > best_pr.estimated_1rm
    new_pr = PR(
        user_id=pr_data.user_id, username=pr_data.username,
        exercise=pr_data.exercise, weight=pr_data.weight,
        reps=pr_data.reps, estimated_1rm=estimated_1rm,
        message_id=pr_data.message_id, channel_id=pr_data.channel_id,
        timestamp=datetime.utcnow()
    )
    db.add(new_pr)
    db.commit()
    db.refresh(new_pr)
    if is_new_pr and XP_ENABLED:
        award_xp_internal(db, pr_data.user_id, pr_data.username, XP_REWARDS_API["pr"], "pr")
    response = PRResponse.from_orm(new_pr)
    response.is_new_pr = is_new_pr
    return response


@app.get("/api/prs/{user_id}", response_model=List[PRResponse], tags=["PRs"])
def get_user_prs(user_id: str, exercise: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db)):
    query = db.query(PR).filter(PR.user_id == user_id)
    if exercise:
        query = query.filter(PR.exercise == exercise)
    prs = query.order_by(PR.timestamp.desc()).limit(limit).all()
    return [PRResponse.from_orm(pr) for pr in prs]


@app.get("/api/prs", response_model=List[PRResponse], tags=["PRs"])
def get_all_prs(limit: int = 1000, db: Session = Depends(get_db)):
    prs = db.query(PR).order_by(PR.timestamp.desc()).limit(limit).all()
    return [PRResponse.from_orm(pr) for pr in prs]


@app.get("/api/prs/{user_id}/best/{exercise}", response_model=Optional[BestPRResponse], tags=["PRs"])
def get_best_pr(user_id: str, exercise: str, db: Session = Depends(get_db)):
    best_pr = _get_best_pr_for_exercise(db, user_id, exercise)
    if not best_pr:
        return None
    return BestPRResponse.from_orm(best_pr)


@app.patch("/api/prs/batch", tags=["PRs"])
def batch_update_pr_exercises(updates: List[dict], db: Session = Depends(get_db)):
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
    return {"updated_count": updated_count, "total_requested": len(updates)}


@app.delete("/api/prs/message/{message_id}", tags=["PRs"])
def delete_prs_by_message(message_id: str, db: Session = Depends(get_db)):
    deleted = db.query(PR).filter(PR.message_id == message_id).delete()
    db.commit()
    return {"deleted_count": deleted, "message_id": message_id}


@app.get("/api/prs/{user_id}/latest", tags=["PRs"])
def get_latest_prs(user_id: str, limit: int = 5, db: Session = Depends(get_db)):
    prs = db.query(PR).filter(PR.user_id == user_id).order_by(PR.timestamp.desc()).limit(limit).all()
    return [{"exercise": pr.exercise, "weight": pr.weight, "reps": pr.reps,
             "estimated_1rm": pr.estimated_1rm, "timestamp": pr.timestamp} for pr in prs]


@app.get("/api/prs/count", tags=["PRs"])
def get_total_pr_count(db: Session = Depends(get_db)):
    from sqlalchemy import func
    return {"total_prs": db.query(func.count(PR.id)).scalar()}


@app.get("/api/prs/{user_id}/count", tags=["PRs"])
def get_user_pr_count(user_id: str, db: Session = Depends(get_db)):
    from sqlalchemy import func
    return {"user_id": user_id, "pr_count": db.query(func.count(PR.id)).filter(PR.user_id == user_id).scalar()}


# ============================================================================
# Workout Plan Endpoints
# ============================================================================

@app.post("/api/workouts", tags=["Workouts"])
def create_workout_plan(plan: WorkoutPlanCreate, db: Session = Depends(get_db)):
    db.query(Workout).filter(
        Workout.user_id == plan.user_id,
        Workout.workout_letter == plan.workout_letter
    ).delete()
    for exercise in plan.exercises:
        db.add(Workout(
            user_id=plan.user_id, workout_letter=plan.workout_letter,
            exercise_order=exercise.exercise_order, exercise_name=exercise.exercise_name,
            setup_notes=exercise.setup_notes, video_link=exercise.video_link,
            special_logging=exercise.special_logging
        ))
    completion = db.query(WorkoutCompletion).filter(
        WorkoutCompletion.user_id == plan.user_id,
        WorkoutCompletion.workout_letter == plan.workout_letter
    ).first()
    if not completion:
        db.add(WorkoutCompletion(
            user_id=plan.user_id, workout_letter=plan.workout_letter, completion_count=0
        ))
    db.commit()
    return {"status": "success", "message": f"Workout {plan.workout_letter} created"}


@app.get("/api/workouts/{user_id}/{workout_letter}", tags=["Workouts"])
def get_workout_plan(user_id: str, workout_letter: str, db: Session = Depends(get_db)):
    return db.query(Workout).filter(
        Workout.user_id == user_id, Workout.workout_letter == workout_letter
    ).order_by(Workout.exercise_order).all()


@app.post("/api/workouts/complete", tags=["Workouts"])
def complete_workout(completion: WorkoutCompletionUpdate, db: Session = Depends(get_db)):
    record = db.query(WorkoutCompletion).filter(
        WorkoutCompletion.user_id == completion.user_id,
        WorkoutCompletion.workout_letter == completion.workout_letter
    ).first()
    if not record:
        record = WorkoutCompletion(
            user_id=completion.user_id, workout_letter=completion.workout_letter, completion_count=0
        )
        db.add(record)
    all_completions = db.query(WorkoutCompletion).filter(
        WorkoutCompletion.user_id == completion.user_id
    ).all()
    last_workout = max([c.last_workout_date for c in all_completions if c.last_workout_date], default=None)
    if last_workout and (datetime.utcnow() - last_workout).days >= 7:
        for c in all_completions:
            c.completion_count = 0
    record.completion_count += 1
    record.last_workout_date = datetime.utcnow()
    member = db.query(DashboardMember).filter(DashboardMember.user_id == completion.user_id).first()
    username = member.username if member else "Unknown"
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
    completions = db.query(WorkoutCompletion).filter(WorkoutCompletion.user_id == user_id).all()
    return [DeloadStatus(workout_letter=c.workout_letter, completion_count=c.completion_count,
                         needs_deload=c.completion_count >= 6) for c in completions]


# ============================================================================
# XP Endpoints
# ============================================================================

def calculate_level(total_xp: int) -> int:
    level = 1
    xp_needed = 500
    remaining_xp = total_xp
    while remaining_xp >= xp_needed:
        remaining_xp -= xp_needed
        level += 1
        xp_needed = 250 + (level * 250)
    return level


def xp_for_next_level(current_level: int) -> int:
    return 250 + (current_level * 250)


def award_xp_internal(db: Session, user_id: str, username: str, xp_amount: int, reason: str):
    user = db.query(UserXP).filter(UserXP.user_id == user_id).first()
    if not user:
        user = UserXP(user_id=user_id, username=username, total_xp=0, level=1)
        db.add(user)
    user.total_xp += xp_amount
    user.level = calculate_level(user.total_xp)
    user.last_updated = datetime.utcnow()
    db.commit()


@app.post("/api/xp/award", response_model=XPResponse, tags=["XP"])
def award_xp(xp_data: XPAward, db: Session = Depends(get_db)):
    if not XP_ENABLED:
        raise HTTPException(status_code=400, detail="XP system is currently disabled")
    award_xp_internal(db, xp_data.user_id, xp_data.username, xp_data.xp_amount, xp_data.reason)
    user = db.query(UserXP).filter(UserXP.user_id == xp_data.user_id).first()
    return XPResponse(user_id=user.user_id, username=user.username, total_xp=user.total_xp,
                      level=user.level, xp_for_next_level=xp_for_next_level(user.level))


@app.get("/api/xp/{user_id}", response_model=XPResponse, tags=["XP"])
def get_user_xp(user_id: str, db: Session = Depends(get_db)):
    user = db.query(UserXP).filter(UserXP.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return XPResponse(user_id=user.user_id, username=user.username, total_xp=user.total_xp,
                      level=user.level, xp_for_next_level=xp_for_next_level(user.level))


# ============================================================================
# Dashboard Member Endpoints
# ============================================================================

@app.post("/api/dashboard/members", response_model=DashboardMemberResponse, tags=["Dashboard"])
def create_dashboard_member(member: DashboardMemberCreate, db: Session = Depends(get_db)):
    existing = db.query(DashboardMember).filter(DashboardMember.user_id == member.user_id).first()
    if existing:
        return DashboardMemberResponse(
            user_id=existing.user_id, username=existing.username, full_name=existing.full_name,
            unique_code=existing.unique_code,
            dashboard_url=f"https://dashboard-production-79f2.up.railway.app/{existing.unique_code}"
        )
    unique_code = secrets.token_urlsafe(16)
    new_member = DashboardMember(
        user_id=member.user_id, username=member.username,
        full_name=member.full_name, unique_code=unique_code
    )
    db.add(new_member)
    db.commit()
    db.refresh(new_member)
    return DashboardMemberResponse(
        user_id=new_member.user_id, username=new_member.username, full_name=new_member.full_name,
        unique_code=new_member.unique_code,
        dashboard_url=f"https://dashboard-production-79f2.up.railway.app/{new_member.unique_code}"
    )


@app.get("/api/dashboard/members/{unique_code}", tags=["Dashboard"])
def get_dashboard_member(unique_code: str, db: Session = Depends(get_db)):
    member = db.query(DashboardMember).filter(DashboardMember.unique_code == unique_code).first()
    if not member:
        raise HTTPException(status_code=404, detail="Invalid dashboard code")
    return member


# ============================================================================
# Dashboard Data Endpoints (unique_code based - used by frontend)
# ============================================================================

@app.get("/api/dashboard/{unique_code}/workouts", tags=["Dashboard"])
def get_dashboard_workouts(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    exercises = db.query(Workout).filter(
        Workout.user_id == member.user_id
    ).order_by(Workout.workout_letter, Workout.exercise_order).all()
    workouts = {}
    for ex in exercises:
        if ex.workout_letter not in workouts:
            workouts[ex.workout_letter] = []
        workouts[ex.workout_letter].append({
            "name": ex.exercise_name, "special_logging": ex.special_logging,
            "setup_notes": ex.setup_notes, "video_link": ex.video_link
        })
    return {"user_id": member.user_id, "username": member.username, "workouts": workouts}


@app.get("/api/dashboard/{unique_code}/best-prs", tags=["Dashboard"])
def get_dashboard_best_prs(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    exercise_names = db.query(PR.exercise).filter(PR.user_id == member.user_id).distinct().all()
    result = {}
    for (exercise_name,) in exercise_names:
        best = _get_best_pr_for_exercise(db, member.user_id, exercise_name)
        if best:
            result[exercise_name] = _format_pr(best)
    return result


@app.get("/api/dashboard/{unique_code}/deload-status", tags=["Dashboard"])
def get_dashboard_deload_status(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    completions = db.query(WorkoutCompletion).filter(
        WorkoutCompletion.user_id == member.user_id
    ).all()
    return {c.workout_letter: c.completion_count for c in completions}


@app.get("/api/dashboard/{unique_code}/core-foods", tags=["Dashboard"])
def get_dashboard_core_foods(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    # Return ALL check-ins (streak calculation needs full history)
    checkins = db.query(CoreFoodsCheckin).filter(
        CoreFoodsCheckin.user_id == member.user_id
    ).all()
    return {c.date: True for c in checkins}


@app.post("/api/dashboard/{unique_code}/core-foods/toggle", tags=["Dashboard"])
def toggle_dashboard_core_foods(unique_code: str, body: dict, db: Session = Depends(get_db)):
    """Toggle a core foods check-in for a date. If exists, delete. If not, create."""
    member = _resolve_member(unique_code, db)
    date = body.get("date")
    if not date:
        raise HTTPException(status_code=400, detail="date required")
    existing = db.query(CoreFoodsCheckin).filter(
        and_(CoreFoodsCheckin.user_id == member.user_id, CoreFoodsCheckin.date == date)
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"checked": False, "date": date}
    checkin = CoreFoodsCheckin(
        user_id=member.user_id, date=date,
        message_id=f"dashboard-{datetime.utcnow().isoformat()}",
        timestamp=datetime.utcnow(), xp_awarded=0
    )
    db.add(checkin)
    db.commit()
    return {"checked": True, "date": date}


@app.post("/api/dashboard/{unique_code}/log", tags=["Dashboard"])
def dashboard_log_exercise(unique_code: str, body: dict, db: Session = Depends(get_db)):
    """
    Log a single exercise from the dashboard.
    Body: { exercise, weight, reps, workout_letter }
    Returns: { is_pr, new_best_pr, estimated_1rm }
    """
    member = _resolve_member(unique_code, db)
    exercise = body.get("exercise", "")
    weight = float(body.get("weight", 0))
    reps = int(body.get("reps", 0))
    workout_letter = body.get("workout_letter", "")
    if not exercise or reps <= 0:
        raise HTTPException(status_code=400, detail="exercise and reps required")

    estimated_1rm = calculate_1rm(weight, reps)

    # Get current best before logging
    best = _get_best_pr_for_exercise(db, member.user_id, exercise)
    if best:
        is_pr = estimated_1rm > best.estimated_1rm if weight > 0 else reps > best.reps
    else:
        is_pr = True

    # Save the log as a PR record
    new_pr = PR(
        user_id=member.user_id, username=member.username,
        exercise=exercise, weight=weight, reps=reps,
        estimated_1rm=estimated_1rm,
        message_id=f"dashboard-{datetime.utcnow().isoformat()}",
        channel_id="dashboard", timestamp=datetime.utcnow()
    )
    db.add(new_pr)

    # Update session tracking
    now = datetime.utcnow()
    session = db.query(WorkoutSession).filter(
        WorkoutSession.user_id == member.user_id,
        WorkoutSession.workout_letter == workout_letter
    ).first()
    if session and (now - session.opened_at).total_seconds() < 96 * 3600:
        session.log_count += 1
    else:
        if session:
            db.delete(session)
        session = WorkoutSession(
            user_id=member.user_id, workout_letter=workout_letter,
            opened_at=now, log_count=1
        )
        db.add(session)

    db.commit()

    # Get updated best
    updated_best = _get_best_pr_for_exercise(db, member.user_id, exercise)
    return {
        "is_pr": is_pr,
        "new_best_pr": _format_pr(updated_best),
        "estimated_1rm": estimated_1rm
    }


@app.post("/api/dashboard/{unique_code}/log-workout", tags=["Dashboard"])
def dashboard_log_workout(unique_code: str, workout_data: dict, db: Session = Depends(get_db)):
    """Legacy batch log endpoint"""
    member = _resolve_member(unique_code, db)
    workout_letter = workout_data.get("workout_letter")
    exercises = workout_data.get("exercises", [])
    core_foods = workout_data.get("core_foods", False)
    for ex in exercises:
        if ex.get("weight", 0) > 0 or ex.get("reps", 0) > 0:
            estimated_1rm = calculate_1rm(ex.get("weight", 0), ex.get("reps", 0))
            db.add(PR(
                user_id=member.user_id, username=member.username,
                exercise=ex["name"], weight=ex.get("weight", 0), reps=ex.get("reps", 0),
                estimated_1rm=estimated_1rm,
                message_id=f"dashboard-{datetime.utcnow().isoformat()}",
                channel_id="dashboard", timestamp=datetime.utcnow()
            ))
    record = db.query(WorkoutCompletion).filter(
        WorkoutCompletion.user_id == member.user_id,
        WorkoutCompletion.workout_letter == workout_letter
    ).first()
    if not record:
        record = WorkoutCompletion(
            user_id=member.user_id, workout_letter=workout_letter, completion_count=0
        )
        db.add(record)
    record.completion_count += 1
    record.last_workout_date = datetime.utcnow()
    if core_foods:
        today = datetime.utcnow().date().isoformat()
        existing_checkin = db.query(CoreFoodsCheckin).filter(
            and_(CoreFoodsCheckin.user_id == member.user_id, CoreFoodsCheckin.date == today)
        ).first()
        if not existing_checkin:
            db.add(CoreFoodsCheckin(
                user_id=member.user_id, date=today,
                message_id=f"dashboard-{datetime.utcnow().isoformat()}",
                timestamp=datetime.utcnow(), xp_awarded=0
            ))
    db.commit()
    return {"success": True, "new_completion_count": record.completion_count, "exercises_logged": len(exercises)}


# ============================================================================
# Dashboard Notes Endpoints
# ============================================================================

@app.get("/api/dashboard/{unique_code}/notes", tags=["Dashboard"])
def get_dashboard_notes(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    notes = db.query(UserNote).filter(UserNote.user_id == member.user_id).all()
    return {n.exercise: n.note for n in notes}


@app.post("/api/dashboard/{unique_code}/notes", tags=["Dashboard"])
def save_dashboard_note(unique_code: str, body: dict, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    exercise = body.get("exercise", "")
    note = body.get("note", "")
    if not exercise:
        raise HTTPException(status_code=400, detail="exercise required")
    existing = db.query(UserNote).filter(
        UserNote.user_id == member.user_id, UserNote.exercise == exercise
    ).first()
    if existing:
        if note.strip():
            existing.note = note
            existing.updated_at = datetime.utcnow()
        else:
            db.delete(existing)
    elif note.strip():
        db.add(UserNote(
            user_id=member.user_id, exercise=exercise,
            note=note, updated_at=datetime.utcnow()
        ))
    db.commit()
    return {"success": True}


# ============================================================================
# Dashboard Swap Endpoints
# ============================================================================

@app.get("/api/dashboard/{unique_code}/swaps", tags=["Dashboard"])
def get_dashboard_swaps(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    swaps = db.query(ExerciseSwap).filter(ExerciseSwap.user_id == member.user_id).all()
    result = {}
    for s in swaps:
        key = f"{s.workout_letter}:{s.exercise_index}"
        result[key] = {"original": s.original_exercise, "swapped": s.swapped_exercise}
    return result


@app.post("/api/dashboard/{unique_code}/swaps", tags=["Dashboard"])
def save_dashboard_swap(unique_code: str, body: dict, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    workout_letter = body.get("workout_letter", "")
    exercise_index = body.get("exercise_index", 0)
    original = body.get("original_exercise", "")
    swapped = body.get("swapped_exercise", "")
    if not workout_letter or not original or not swapped:
        raise HTTPException(status_code=400, detail="workout_letter, original_exercise, swapped_exercise required")
    existing = db.query(ExerciseSwap).filter(
        ExerciseSwap.user_id == member.user_id,
        ExerciseSwap.workout_letter == workout_letter,
        ExerciseSwap.exercise_index == exercise_index
    ).first()
    if existing:
        existing.swapped_exercise = swapped
        existing.created_at = datetime.utcnow()
    else:
        db.add(ExerciseSwap(
            user_id=member.user_id, workout_letter=workout_letter,
            exercise_index=exercise_index, original_exercise=original,
            swapped_exercise=swapped, created_at=datetime.utcnow()
        ))
    db.commit()
    return {"success": True}


@app.delete("/api/dashboard/{unique_code}/swaps", tags=["Dashboard"])
def revert_dashboard_swap(unique_code: str, body: dict, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    workout_letter = body.get("workout_letter", "")
    exercise_index = body.get("exercise_index", 0)
    db.query(ExerciseSwap).filter(
        ExerciseSwap.user_id == member.user_id,
        ExerciseSwap.workout_letter == workout_letter,
        ExerciseSwap.exercise_index == exercise_index
    ).delete()
    db.commit()
    return {"success": True}


# ============================================================================
# Dashboard PR History (for graphs)
# ============================================================================

@app.get("/api/dashboard/{unique_code}/pr-history/{exercise}", tags=["Dashboard"])
def get_dashboard_pr_history(unique_code: str, exercise: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    prs = db.query(PR).filter(
        PR.user_id == member.user_id,
        PR.exercise == exercise
    ).order_by(PR.timestamp.asc()).all()
    return [
        {"weight": pr.weight, "reps": pr.reps, "estimated_1rm": pr.estimated_1rm,
         "timestamp": pr.timestamp.isoformat()}
        for pr in prs
    ]


# ============================================================================
# Dashboard Sessions
# ============================================================================

@app.get("/api/dashboard/{unique_code}/sessions", tags=["Dashboard"])
def get_dashboard_sessions(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    sessions = db.query(WorkoutSession).filter(
        WorkoutSession.user_id == member.user_id
    ).all()
    now = datetime.utcnow()
    result = {}
    for s in sessions:
        elapsed = (now - s.opened_at).total_seconds()
        if elapsed < 96 * 3600:
            result[s.workout_letter] = {
                "opened_at": s.opened_at.isoformat(),
                "log_count": s.log_count
            }
    return result


# ============================================================================
# Full Dashboard Data (single fetch on mount)
# ============================================================================

@app.get("/api/dashboard/{unique_code}/full", tags=["Dashboard"])
def get_full_dashboard(unique_code: str, db: Session = Depends(get_db)):
    """Single endpoint that returns everything the dashboard needs on mount."""
    member = _resolve_member(unique_code, db)
    uid = member.user_id

    # Workouts
    exercises = db.query(Workout).filter(
        Workout.user_id == uid
    ).order_by(Workout.workout_letter, Workout.exercise_order).all()
    workouts = {}
    for ex in exercises:
        if ex.workout_letter not in workouts:
            workouts[ex.workout_letter] = []
        workouts[ex.workout_letter].append({
            "name": ex.exercise_name, "special_logging": ex.special_logging,
            "setup_notes": ex.setup_notes, "video_link": ex.video_link
        })

    # Best PRs
    exercise_names = db.query(PR.exercise).filter(PR.user_id == uid).distinct().all()
    best_prs = {}
    for (name,) in exercise_names:
        best = _get_best_pr_for_exercise(db, uid, name)
        if best:
            best_prs[name] = _format_pr(best)

    # Deload status
    completions = db.query(WorkoutCompletion).filter(WorkoutCompletion.user_id == uid).all()
    deload = {c.workout_letter: c.completion_count for c in completions}
    last_workout_dates = {}
    for c in completions:
        if c.last_workout_date:
            last_workout_dates[c.workout_letter] = c.last_workout_date.isoformat()

    # Core foods (all history for streak)
    checkins = db.query(CoreFoodsCheckin).filter(CoreFoodsCheckin.user_id == uid).all()
    core_foods = {c.date: True for c in checkins}

    # Notes
    notes_rows = db.query(UserNote).filter(UserNote.user_id == uid).all()
    notes = {n.exercise: n.note for n in notes_rows}

    # Swaps
    swap_rows = db.query(ExerciseSwap).filter(ExerciseSwap.user_id == uid).all()
    swaps = {}
    for s in swap_rows:
        key = f"{s.workout_letter}:{s.exercise_index}"
        swaps[key] = {"original": s.original_exercise, "swapped": s.swapped_exercise}

    # Sessions (active only)
    now = datetime.utcnow()
    session_rows = db.query(WorkoutSession).filter(WorkoutSession.user_id == uid).all()
    sessions = {}
    for s in session_rows:
        if (now - s.opened_at).total_seconds() < 96 * 3600:
            sessions[s.workout_letter] = {
                "opened_at": s.opened_at.isoformat(),
                "log_count": s.log_count
            }

    return {
        "username": member.username,
        "workouts": workouts,
        "best_prs": best_prs,
        "deload": deload,
        "last_workout_dates": last_workout_dates,
        "core_foods": core_foods,
        "notes": notes,
        "swaps": swaps,
        "sessions": sessions
    }


# ============================================================================
# Weekly Logs Endpoints
# ============================================================================

@app.post("/api/weekly-logs", tags=["Weekly Logs"])
def record_weekly_log(user_id: str, message_id: str, xp_awarded: int, db: Session = Depends(get_db)):
    db.add(WeeklyLog(user_id=user_id, message_id=message_id, timestamp=datetime.utcnow(), xp_awarded=xp_awarded))
    db.commit()
    return {"success": True, "xp_awarded": xp_awarded}


@app.get("/api/weekly-logs/{user_id}/can-submit", tags=["Weekly Logs"])
def can_submit_weekly_log(user_id: str, db: Session = Depends(get_db)):
    last_log = db.query(WeeklyLog).filter(WeeklyLog.user_id == user_id).order_by(WeeklyLog.timestamp.desc()).first()
    if not last_log:
        return {"can_submit": True, "days_since_last": None}
    days_since = (datetime.utcnow() - last_log.timestamp).days
    return {"can_submit": days_since >= 6, "days_since_last": days_since}


# ============================================================================
# Core Foods Endpoints
# ============================================================================

@app.post("/api/core-foods", tags=["Core Foods"])
def record_core_foods_checkin(
    user_id: str, message_id: str, xp_awarded: int,
    date: Optional[str] = None, protein_servings: Optional[int] = None,
    veggie_servings: Optional[int] = None, db: Session = Depends(get_db)
):
    if date is None:
        target_date = datetime.utcnow().date()
        date = target_date.isoformat()
    else:
        try:
            target_date = datetime.fromisoformat(date).date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    today = datetime.utcnow().date()
    if target_date > today:
        raise HTTPException(status_code=400, detail="Cannot log future dates")
    days_ago = (today - target_date).days
    if days_ago > 2:
        raise HTTPException(status_code=400, detail=f"Cannot log dates more than 2 days ago")
    existing = db.query(CoreFoodsCheckin).filter(
        and_(CoreFoodsCheckin.user_id == user_id, CoreFoodsCheckin.date == date)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Already checked in for {date}")
    if protein_servings is not None and (protein_servings < 0 or protein_servings > 4):
        raise HTTPException(status_code=400, detail="Protein servings must be 0-4")
    if veggie_servings is not None and (veggie_servings < 0 or veggie_servings > 3):
        raise HTTPException(status_code=400, detail="Veggie servings must be 0-3")
    checkin = CoreFoodsCheckin(
        user_id=user_id, date=date, message_id=message_id,
        timestamp=datetime.utcnow(), xp_awarded=xp_awarded,
        protein_servings=protein_servings, veggie_servings=veggie_servings
    )
    db.add(checkin)
    db.commit()
    return {"success": True, "date": date, "days_ago": days_ago, "xp_awarded": xp_awarded,
            "mode": "learning" if protein_servings is not None else "simple"}


@app.get("/api/core-foods/{user_id}/can-checkin", tags=["Core Foods"])
def can_checkin_core_foods(user_id: str, db: Session = Depends(get_db)):
    today = datetime.utcnow().date().isoformat()
    existing = db.query(CoreFoodsCheckin).filter(
        and_(CoreFoodsCheckin.user_id == user_id, CoreFoodsCheckin.date == today)
    ).first()
    return {"can_checkin": existing is None}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
