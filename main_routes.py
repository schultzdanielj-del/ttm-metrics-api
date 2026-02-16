"""
TTM Metrics API - All route definitions
Split from main.py for manageability
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import datetime, timedelta
import secrets
import re
import os

from database import (
    get_db, PR, Workout, WorkoutCompletion, UserXP,
    DashboardMember, CoreFoodsLog as CoreFoodsLogModel, WeeklyLog,
    CoreFoodsCheckin, UserNote, ExerciseSwap, WorkoutSession,
    SessionLocal
)
from schemas import (
    PRCreate, PRResponse, BestPRResponse,
    WorkoutPlanCreate, WorkoutCompletionUpdate, DeloadStatus,
    XPAward, XPResponse,
    DashboardMemberCreate, DashboardMemberResponse,
    CoreFoodsLog
)
from config import XP_REWARDS_API, XP_ENABLED

router = APIRouter()


@router.get("/")
def root():
    return {"status": "healthy", "service": "TTM Metrics API", "version": "1.5.8"}


_STRIP_WORDS = {
    'grip', 'machine', 'cable', 'loaded', 'the', 'a', 'an', 'with', 'on',
    'non', 'alternating', 'style',
}

_EXPANSIONS = {
    'db': 'dumbbell', 'rdf': 'rear delt fly', 'uh': 'underhand',
    'oh': 'overhead', 'bb': 'barbell', 'bw': 'bodyweight', 'atg': 'ass to grass',
}


def _normalize_exercise_key(name: str) -> str:
    k = name.lower().strip()
    k = re.sub(r'[^a-z0-9\s]', ' ', k)
    k = re.sub(r'\s+', ' ', k)
    tokens = k.split()
    expanded = []
    for t in tokens:
        if t in _EXPANSIONS:
            expanded.extend(_EXPANSIONS[t].split())
        else:
            expanded.append(t)
    singularized = []
    for t in expanded:
        for plural, singular in [
            ('pulldowns', 'pulldown'), ('pullups', 'pullup'), ('chinups', 'chinup'),
            ('curls', 'curl'), ('raises', 'raise'), ('rows', 'row'),
            ('flys', 'fly'), ('flies', 'fly'), ('extensions', 'extension'),
            ('pushdowns', 'pushdown'), ('lunges', 'lunge'), ('squats', 'squat'),
            ('thrusts', 'thrust'), ('bridges', 'bridge'), ('planks', 'plank'),
            ('situps', 'situp'), ('crunches', 'crunch'), ('hypers', 'hyper'),
            ('shrugs', 'shrug'), ('skullcrushers', 'skullcrusher'), ('presses', 'press'),
            ('rollouts', 'rollout'), ('rotations', 'rotation'),
        ]:
            if t == plural:
                t = singular
                break
        singularized.append(t)
    cleaned = [t for t in singularized if t not in _STRIP_WORDS and len(t) > 0]
    return ' '.join(sorted(cleaned))


def _exercise_similarity(name_a: str, name_b: str) -> float:
    nk_a = _normalize_exercise_key(name_a)
    nk_b = _normalize_exercise_key(name_b)
    if nk_a == nk_b:
        return 1.0
    tokens_a = set(nk_a.split())
    tokens_b = set(nk_b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = tokens_a & tokens_b
    min_len = min(len(tokens_a), len(tokens_b))
    return len(overlap) / min_len if min_len > 0 else 0.0


def _find_all_matching_names(db: Session, user_id: str, exercise_name: str) -> List[str]:
    """Exact match only. All PR exercise names are canonical as of session 14."""
    exists = db.query(PR.exercise).filter(
        PR.user_id == user_id, PR.exercise == exercise_name
    ).first()
    return [exercise_name] if exists else []


def calculate_1rm(weight: float, reps: int) -> float:
    if weight == 0:
        return reps
    return (weight * reps * 0.0333) + weight


def _resolve_member(unique_code: str, db: Session) -> DashboardMember:
    member = db.query(DashboardMember).filter(DashboardMember.unique_code == unique_code).first()
    if not member:
        raise HTTPException(status_code=404, detail="Not Found")
    return member


def _get_best_pr_for_exercise(db: Session, user_id: str, exercise: str):
    return db.query(PR).filter(PR.user_id == user_id, PR.exercise == exercise).order_by(PR.estimated_1rm.desc()).first()


def _get_best_pr_across_names(db: Session, user_id: str, names: List[str]):
    if not names:
        return None
    return db.query(PR).filter(PR.user_id == user_id, PR.exercise.in_(names)).order_by(PR.estimated_1rm.desc()).first()


def _format_pr(pr) -> str:
    if not pr:
        return None
    if pr.weight == 0:
        return f"BW/{pr.reps}"
    w = int(pr.weight) if pr.weight == int(pr.weight) else pr.weight
    return f"{w}/{pr.reps}"


def _find_best_pr_match(db: Session, user_id: str, workout_exercise_name: str):
    best = db.query(PR).filter(
        PR.user_id == user_id, PR.exercise == workout_exercise_name
    ).order_by(PR.estimated_1rm.desc()).first()
    if best:
        return best, best.exercise
    return None, None


def _build_best_prs_for_workouts(db: Session, user_id: str, workouts: dict) -> dict:
    best_prs = {}
    for letter, exercises in workouts.items():
        for ex in exercises:
            workout_name = ex["name"]
            if workout_name in best_prs:
                continue
            best = db.query(PR).filter(
                PR.user_id == user_id, PR.exercise == workout_name
            ).order_by(PR.estimated_1rm.desc()).first()
            if best:
                best_prs[workout_name] = _format_pr(best)
    return best_prs


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


@router.post("/api/prs", response_model=PRResponse, tags=["PRs"])
def log_pr(pr_data: PRCreate, db: Session = Depends(get_db)):
    estimated_1rm = calculate_1rm(pr_data.weight, pr_data.reps)
    if pr_data.weight == 0:
        best_pr = db.query(PR).filter(PR.user_id == pr_data.user_id, PR.exercise == pr_data.exercise, PR.weight == 0).order_by(PR.estimated_1rm.desc()).first()
    else:
        best_pr = db.query(PR).filter(PR.user_id == pr_data.user_id, PR.exercise == pr_data.exercise, PR.weight > 0).order_by(PR.estimated_1rm.desc()).first()
    is_new_pr = not best_pr or estimated_1rm > best_pr.estimated_1rm
    new_pr = PR(user_id=pr_data.user_id, username=pr_data.username, exercise=pr_data.exercise, weight=pr_data.weight, reps=pr_data.reps, estimated_1rm=estimated_1rm, message_id=pr_data.message_id, channel_id=pr_data.channel_id, timestamp=datetime.utcnow())
    db.add(new_pr)
    db.commit()
    db.refresh(new_pr)
    if is_new_pr and XP_ENABLED:
        award_xp_internal(db, pr_data.user_id, pr_data.username, XP_REWARDS_API["pr"], "pr")
    response = PRResponse.from_orm(new_pr)
    response.is_new_pr = is_new_pr
    return response


@router.get("/api/prs/{user_id}", response_model=List[PRResponse], tags=["PRs"])
def get_user_prs(user_id: str, exercise: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db)):
    query = db.query(PR).filter(PR.user_id == user_id)
    if exercise:
        query = query.filter(PR.exercise == exercise)
    return [PRResponse.from_orm(pr) for pr in query.order_by(PR.timestamp.desc()).limit(limit).all()]


@router.get("/api/prs", response_model=List[PRResponse], tags=["PRs"])
def get_all_prs(limit: int = 1000, db: Session = Depends(get_db)):
    return [PRResponse.from_orm(pr) for pr in db.query(PR).order_by(PR.timestamp.desc()).limit(limit).all()]


@router.get("/api/prs/{user_id}/best/{exercise}", response_model=Optional[BestPRResponse], tags=["PRs"])
def get_best_pr(user_id: str, exercise: str, db: Session = Depends(get_db)):
    best_pr = _get_best_pr_for_exercise(db, user_id, exercise)
    return BestPRResponse.from_orm(best_pr) if best_pr else None


@router.patch("/api/prs/batch", tags=["PRs"])
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


@router.delete("/api/prs/message/{message_id}", tags=["PRs"])
def delete_prs_by_message(message_id: str, db: Session = Depends(get_db)):
    deleted = db.query(PR).filter(PR.message_id == message_id).delete()
    db.commit()
    return {"deleted_count": deleted, "message_id": message_id}


@router.get("/api/prs/{user_id}/latest", tags=["PRs"])
def get_latest_prs(user_id: str, limit: int = 5, db: Session = Depends(get_db)):
    prs = db.query(PR).filter(PR.user_id == user_id).order_by(PR.timestamp.desc()).limit(limit).all()
    return [{"exercise": pr.exercise, "weight": pr.weight, "reps": pr.reps, "estimated_1rm": pr.estimated_1rm, "timestamp": pr.timestamp} for pr in prs]


@router.get("/api/prs/count", tags=["PRs"])
def get_total_pr_count(db: Session = Depends(get_db)):
    from sqlalchemy import func
    return {"total_prs": db.query(func.count(PR.id)).scalar()}


@router.get("/api/prs/{user_id}/count", tags=["PRs"])
def get_user_pr_count(user_id: str, db: Session = Depends(get_db)):
    from sqlalchemy import func
    return {"user_id": user_id, "pr_count": db.query(func.count(PR.id)).filter(PR.user_id == user_id).scalar()}


@router.post("/api/workouts", tags=["Workouts"])
def create_workout_plan(plan: WorkoutPlanCreate, db: Session = Depends(get_db)):
    db.query(Workout).filter(Workout.user_id == plan.user_id, Workout.workout_letter == plan.workout_letter).delete()
    for exercise in plan.exercises:
        db.add(Workout(user_id=plan.user_id, workout_letter=plan.workout_letter, exercise_order=exercise.exercise_order, exercise_name=exercise.exercise_name, setup_notes=exercise.setup_notes, video_link=exercise.video_link, special_logging=exercise.special_logging))
    completion = db.query(WorkoutCompletion).filter(WorkoutCompletion.user_id == plan.user_id, WorkoutCompletion.workout_letter == plan.workout_letter).first()
    if not completion:
        db.add(WorkoutCompletion(user_id=plan.user_id, workout_letter=plan.workout_letter, completion_count=0))
    db.commit()
    return {"status": "success", "message": f"Workout {plan.workout_letter} created"}


@router.get("/api/workouts/{user_id}/{workout_letter}", tags=["Workouts"])
def get_workout_plan(user_id: str, workout_letter: str, db: Session = Depends(get_db)):
    return db.query(Workout).filter(Workout.user_id == user_id, Workout.workout_letter == workout_letter).order_by(Workout.exercise_order).all()


@router.post("/api/workouts/complete", tags=["Workouts"])
def complete_workout(completion: WorkoutCompletionUpdate, db: Session = Depends(get_db)):
    record = db.query(WorkoutCompletion).filter(WorkoutCompletion.user_id == completion.user_id, WorkoutCompletion.workout_letter == completion.workout_letter).first()
    if not record:
        record = WorkoutCompletion(user_id=completion.user_id, workout_letter=completion.workout_letter, completion_count=0)
        db.add(record)
    all_completions = db.query(WorkoutCompletion).filter(WorkoutCompletion.user_id == completion.user_id).all()
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
    return {"workout_letter": record.workout_letter, "completion_count": record.completion_count, "needs_deload": record.completion_count >= 6, "xp_awarded": XP_REWARDS_API["workout_complete"] if XP_ENABLED else 0}


@router.get("/api/workouts/{user_id}/deload-status", response_model=List[DeloadStatus], tags=["Workouts"])
def get_deload_status(user_id: str, db: Session = Depends(get_db)):
    completions = db.query(WorkoutCompletion).filter(WorkoutCompletion.user_id == user_id).all()
    return [DeloadStatus(workout_letter=c.workout_letter, completion_count=c.completion_count, needs_deload=c.completion_count >= 6) for c in completions]


@router.post("/api/xp/award", response_model=XPResponse, tags=["XP"])
def award_xp(xp_data: XPAward, db: Session = Depends(get_db)):
    if not XP_ENABLED:
        raise HTTPException(status_code=400, detail="XP system is currently disabled")
    award_xp_internal(db, xp_data.user_id, xp_data.username, xp_data.xp_amount, xp_data.reason)
    user = db.query(UserXP).filter(UserXP.user_id == xp_data.user_id).first()
    return XPResponse(user_id=user.user_id, username=user.username, total_xp=user.total_xp, level=user.level, xp_for_next_level=xp_for_next_level(user.level))


@router.get("/api/xp/{user_id}", response_model=XPResponse, tags=["XP"])
def get_user_xp(user_id: str, db: Session = Depends(get_db)):
    user = db.query(UserXP).filter(UserXP.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return XPResponse(user_id=user.user_id, username=user.username, total_xp=user.total_xp, level=user.level, xp_for_next_level=xp_for_next_level(user.level))


@router.post("/api/dashboard/members", response_model=DashboardMemberResponse, tags=["Dashboard"])
def create_dashboard_member(member: DashboardMemberCreate, db: Session = Depends(get_db)):
    existing = db.query(DashboardMember).filter(DashboardMember.user_id == member.user_id).first()
    if existing:
        return DashboardMemberResponse(user_id=existing.user_id, username=existing.username, full_name=existing.full_name, unique_code=existing.unique_code, dashboard_url=f"https://dashboard-production-79f2.up.railway.app/{existing.unique_code}")
    unique_code = secrets.token_urlsafe(16)
    new_member = DashboardMember(user_id=member.user_id, username=member.username, full_name=member.full_name, unique_code=unique_code)
    db.add(new_member)
    db.commit()
    db.refresh(new_member)
    return DashboardMemberResponse(user_id=new_member.user_id, username=new_member.username, full_name=new_member.full_name, unique_code=new_member.unique_code, dashboard_url=f"https://dashboard-production-79f2.up.railway.app/{new_member.unique_code}")


@router.patch("/api/dashboard/members/{unique_code}", tags=["Dashboard"])
def update_dashboard_member(unique_code: str, body: dict, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    if "username" in body:
        member.username = body["username"]
    if "full_name" in body:
        member.full_name = body["full_name"]
    db.commit()
    db.refresh(member)
    return {"user_id": member.user_id, "username": member.username, "full_name": member.full_name, "unique_code": member.unique_code}


@router.get("/api/dashboard/members/{unique_code}", tags=["Dashboard"])
def get_dashboard_member(unique_code: str, db: Session = Depends(get_db)):
    member = db.query(DashboardMember).filter(DashboardMember.unique_code == unique_code).first()
    if not member:
        raise HTTPException(status_code=404, detail="Invalid dashboard code")
    return member


@router.get("/api/dashboard/members", tags=["Dashboard"])
def list_all_members(db: Session = Depends(get_db)):
    members = db.query(DashboardMember).order_by(DashboardMember.created_at).all()
    return [{"user_id": m.user_id, "username": m.username, "full_name": m.full_name, "unique_code": m.unique_code, "dashboard_url": f"https://dashboard-production-79f2.up.railway.app/{m.unique_code}"} for m in members]
