"""
TTM Metrics API - Dashboard and admin route definitions (part 2)
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import datetime, timedelta
import os

from database import (
    get_db, PR, Workout, WorkoutCompletion, UserXP,
    DashboardMember, CoreFoodsLog as CoreFoodsLogModel, WeeklyLog,
    CoreFoodsCheckin, UserNote, ExerciseSwap, WorkoutSession,
    CoachMessage, SessionLocal
)
from carousel import build_carousel_state, check_inactivity_reset, _get_workout_letters, calculate_strength_gains
from schemas import (
    PRCreate, PRResponse, BestPRResponse,
    WorkoutPlanCreate, WorkoutCompletionUpdate, DeloadStatus,
    XPAward, XPResponse,
    DashboardMemberCreate, DashboardMemberResponse,
    CoreFoodsLog
)
from config import XP_REWARDS_API, XP_ENABLED
from main_routes import (
    _resolve_member, _get_best_pr_for_exercise, _get_best_pr_across_names,
    _format_pr, _find_all_matching_names, _build_best_prs_for_workouts,
    calculate_1rm, _normalize_exercise_key, award_xp_internal
)
from discord_notifications import post_core_foods_notification, post_pr_notification, delete_pr_notification
from coach_messages import get_coach_messages_for_user

router = APIRouter()


@router.get("/api/dashboard/{unique_code}/workouts", tags=["Dashboard"])
def get_dashboard_workouts(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    exercises = db.query(Workout).filter(Workout.user_id == member.user_id).order_by(Workout.workout_letter, Workout.exercise_order).all()
    workouts = {}
    for ex in exercises:
        if ex.workout_letter not in workouts:
            workouts[ex.workout_letter] = []
        workouts[ex.workout_letter].append({"name": ex.exercise_name, "special_logging": ex.special_logging, "setup_notes": ex.setup_notes, "video_link": ex.video_link})
    return {"user_id": member.user_id, "username": member.username, "workouts": workouts}


@router.get("/api/dashboard/{unique_code}/best-prs", tags=["Dashboard"])
def get_dashboard_best_prs(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    exercise_names = db.query(PR.exercise).filter(PR.user_id == member.user_id).distinct().all()
    result = {}
    for (exercise_name,) in exercise_names:
        best = _get_best_pr_for_exercise(db, member.user_id, exercise_name)
        if best:
            result[exercise_name] = _format_pr(best)
    return result


@router.get("/api/dashboard/{unique_code}/deload-status", tags=["Dashboard"])
def get_dashboard_deload_status(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    completions = db.query(WorkoutCompletion).filter(WorkoutCompletion.user_id == member.user_id).all()
    return {c.workout_letter: c.completion_count for c in completions}


@router.get("/api/dashboard/{unique_code}/core-foods", tags=["Dashboard"])
def get_dashboard_core_foods(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    checkins = db.query(CoreFoodsCheckin).filter(CoreFoodsCheckin.user_id == member.user_id).all()
    return {c.date: True for c in checkins}


@router.post("/api/dashboard/{unique_code}/core-foods/toggle", tags=["Dashboard"])
def toggle_dashboard_core_foods(unique_code: str, body: dict, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    date = body.get("date")
    if not date:
        raise HTTPException(status_code=400, detail="date required")
    existing = db.query(CoreFoodsCheckin).filter(and_(CoreFoodsCheckin.user_id == member.user_id, CoreFoodsCheckin.date == date)).first()
    if existing:
        db.delete(existing)
        db.commit()
        post_core_foods_notification(db, member.user_id, date, checked=False)
        return {"checked": False, "date": date}
    checkin = CoreFoodsCheckin(user_id=member.user_id, date=date, message_id=f"dashboard-{datetime.utcnow().isoformat()}", timestamp=datetime.utcnow(), xp_awarded=0)
    db.add(checkin)
    db.commit()
    post_core_foods_notification(db, member.user_id, date, checked=True)
    return {"checked": True, "date": date}


@router.post("/api/dashboard/{unique_code}/log", tags=["Dashboard"])
def dashboard_log_exercise(unique_code: str, body: dict, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    exercise = body.get("exercise", "")
    weight = float(body.get("weight", 0))
    reps = int(body.get("reps", 0))
    workout_letter = body.get("workout_letter", "")
    slot_index = body.get("slot_index")  # which input slot on the dashboard (0, 1, 2...)
    if not exercise or reps <= 0:
        raise HTTPException(status_code=400, detail="exercise and reps required")
    estimated_1rm = calculate_1rm(weight, reps)
    matching_names = _find_all_matching_names(db, member.user_id, exercise)
    store_as = exercise
    if matching_names:
        existing = db.query(PR).filter(PR.user_id == member.user_id, PR.exercise.in_(matching_names)).first()
        if existing:
            store_as = existing.exercise

    # Build message_id with slot info for dashboard logs
    slot_tag = f"slot{slot_index}-" if slot_index is not None else ""
    msg_id = f"dashboard-{slot_tag}{datetime.utcnow().isoformat()}"

    # Find active session
    now = datetime.utcnow()
    session = db.query(WorkoutSession).filter(WorkoutSession.user_id == member.user_id, WorkoutSession.workout_letter == workout_letter).first()
    session_opened = None
    if session and (now - session.opened_at).total_seconds() < 96 * 3600:
        session_opened = session.opened_at
    
    # Delete any existing PR row for this exercise+slot within the current session
    prev_in_session = None
    if session_opened:
        q = db.query(PR).filter(
            PR.user_id == member.user_id,
            PR.exercise == store_as,
            PR.timestamp >= session_opened,
            PR.channel_id == "dashboard"
        )
        # If slot_index provided, only overwrite the same slot
        if slot_index is not None:
            q = q.filter(PR.message_id.like(f"dashboard-slot{slot_index}-%"))
        prev_in_session = q.first()
        if prev_in_session:
            db.delete(prev_in_session)
            db.flush()

    # Now evaluate PR against best excluding the just-deleted row
    all_names = _find_all_matching_names(db, member.user_id, store_as)
    best = _get_best_pr_across_names(db, member.user_id, all_names) if all_names else None
    old_1rm = best.estimated_1rm if best else None
    is_pr = (estimated_1rm > best.estimated_1rm if weight > 0 else reps > best.reps) if best else True

    # Insert new PR row
    new_pr = PR(user_id=member.user_id, username=member.username, exercise=store_as, weight=weight, reps=reps, estimated_1rm=estimated_1rm, message_id=msg_id, channel_id="dashboard", timestamp=datetime.utcnow())
    db.add(new_pr)

    # Update session
    if session_opened:
        session.log_count = session.log_count  # session already active, count stays (replace not add)
    else:
        if session:
            db.delete(session)
        session = WorkoutSession(user_id=member.user_id, workout_letter=workout_letter, opened_at=now, log_count=1)
        db.add(session)
    db.commit()

    # Discord notifications
    if is_pr and old_1rm is not None:
        post_pr_notification(db, member.user_id, store_as, old_1rm, estimated_1rm)
    elif not is_pr and prev_in_session is not None:
        # Previous log may have posted a PR notification, clean it up
        delete_pr_notification(db, member.user_id, store_as)

    all_names = _find_all_matching_names(db, member.user_id, store_as)
    updated_best = _get_best_pr_across_names(db, member.user_id, all_names) if all_names else None
    return {"is_pr": is_pr, "new_best_pr": _format_pr(updated_best), "estimated_1rm": estimated_1rm}


@router.post("/api/dashboard/{unique_code}/log-workout", tags=["Dashboard"])
def dashboard_log_workout(unique_code: str, workout_data: dict, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    workout_letter = workout_data.get("workout_letter")
    exercises = workout_data.get("exercises", [])
    core_foods = workout_data.get("core_foods", False)
    for ex in exercises:
        if ex.get("weight", 0) > 0 or ex.get("reps", 0) > 0:
            estimated_1rm = calculate_1rm(ex.get("weight", 0), ex.get("reps", 0))
            db.add(PR(user_id=member.user_id, username=member.username, exercise=ex["name"], weight=ex.get("weight", 0), reps=ex.get("reps", 0), estimated_1rm=estimated_1rm, message_id=f"dashboard-{datetime.utcnow().isoformat()}", channel_id="dashboard", timestamp=datetime.utcnow()))
    record = db.query(WorkoutCompletion).filter(WorkoutCompletion.user_id == member.user_id, WorkoutCompletion.workout_letter == workout_letter).first()
    if not record:
        record = WorkoutCompletion(user_id=member.user_id, workout_letter=workout_letter, completion_count=0)
        db.add(record)
    record.completion_count += 1
    record.last_workout_date = datetime.utcnow()
    if core_foods:
        today = datetime.utcnow().date().isoformat()
        existing_checkin = db.query(CoreFoodsCheckin).filter(and_(CoreFoodsCheckin.user_id == member.user_id, CoreFoodsCheckin.date == today)).first()
        if not existing_checkin:
            db.add(CoreFoodsCheckin(user_id=member.user_id, date=today, message_id=f"dashboard-{datetime.utcnow().isoformat()}", timestamp=datetime.utcnow(), xp_awarded=0))
    db.commit()
    return {"success": True, "new_completion_count": record.completion_count, "exercises_logged": len(exercises)}


@router.get("/api/dashboard/{unique_code}/notes", tags=["Dashboard"])
def get_dashboard_notes(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    notes = db.query(UserNote).filter(UserNote.user_id == member.user_id).all()
    return {n.exercise: n.note for n in notes}


@router.post("/api/dashboard/{unique_code}/notes", tags=["Dashboard"])
def save_dashboard_note(unique_code: str, body: dict, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    exercise = body.get("exercise", "")
    note = body.get("note", "")
    if not exercise:
        raise HTTPException(status_code=400, detail="exercise required")
    existing = db.query(UserNote).filter(UserNote.user_id == member.user_id, UserNote.exercise == exercise).first()
    if existing:
        if note.strip():
            existing.note = note
            existing.updated_at = datetime.utcnow()
        else:
            db.delete(existing)
    elif note.strip():
        db.add(UserNote(user_id=member.user_id, exercise=exercise, note=note, updated_at=datetime.utcnow()))
    db.commit()
    return {"success": True}


@router.get("/api/dashboard/{unique_code}/swaps", tags=["Dashboard"])
def get_dashboard_swaps(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    swaps = db.query(ExerciseSwap).filter(ExerciseSwap.user_id == member.user_id).all()
    result = {}
    for s in swaps:
        key = f"{s.workout_letter}:{s.exercise_index}"
        result[key] = {"original": s.original_exercise, "swapped": s.swapped_exercise}
    return result


@router.post("/api/dashboard/{unique_code}/swaps", tags=["Dashboard"])
def save_dashboard_swap(unique_code: str, body: dict, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    workout_letter = body.get("workout_letter", "")
    exercise_index = body.get("exercise_index", 0)
    original = body.get("original_exercise", "")
    swapped = body.get("swapped_exercise", "")
    if not workout_letter or not original or not swapped:
        raise HTTPException(status_code=400, detail="workout_letter, original_exercise, swapped_exercise required")
    existing = db.query(ExerciseSwap).filter(ExerciseSwap.user_id == member.user_id, ExerciseSwap.workout_letter == workout_letter, ExerciseSwap.exercise_index == exercise_index).first()
    if existing:
        existing.swapped_exercise = swapped
        existing.created_at = datetime.utcnow()
    else:
        db.add(ExerciseSwap(user_id=member.user_id, workout_letter=workout_letter, exercise_index=exercise_index, original_exercise=original, swapped_exercise=swapped, created_at=datetime.utcnow()))
    db.commit()
    return {"success": True}


@router.delete("/api/dashboard/{unique_code}/swaps", tags=["Dashboard"])
def revert_dashboard_swap(unique_code: str, body: dict, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    workout_letter = body.get("workout_letter", "")
    exercise_index = body.get("exercise_index", 0)
    db.query(ExerciseSwap).filter(ExerciseSwap.user_id == member.user_id, ExerciseSwap.workout_letter == workout_letter, ExerciseSwap.exercise_index == exercise_index).delete()
    db.commit()
    return {"success": True}


@router.get("/api/dashboard/{unique_code}/pr-history/{exercise}", tags=["Dashboard"])
def get_dashboard_pr_history(unique_code: str, exercise: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    matching_names = _find_all_matching_names(db, member.user_id, exercise)
    if not matching_names:
        return []
    prs = db.query(PR).filter(PR.user_id == member.user_id, PR.exercise.in_(matching_names)).order_by(PR.timestamp.asc()).all()
    return [{"weight": pr.weight, "reps": pr.reps, "estimated_1rm": pr.estimated_1rm, "timestamp": pr.timestamp.isoformat()} for pr in prs]


@router.get("/api/dashboard/{unique_code}/sessions", tags=["Dashboard"])
def get_dashboard_sessions(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    sessions = db.query(WorkoutSession).filter(WorkoutSession.user_id == member.user_id).all()
    now = datetime.utcnow()
    result = {}
    for s in sessions:
        if (now - s.opened_at).total_seconds() < 96 * 3600:
            result[s.workout_letter] = {"opened_at": s.opened_at.isoformat(), "log_count": s.log_count}
    return result


@router.get("/api/dashboard/{unique_code}/full", tags=["Dashboard"])
def get_full_dashboard(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    uid = member.user_id
    exercises = db.query(Workout).filter(Workout.user_id == uid).order_by(Workout.workout_letter, Workout.exercise_order).all()
    workouts = {}
    for ex in exercises:
        if ex.workout_letter not in workouts:
            workouts[ex.workout_letter] = []
        workouts[ex.workout_letter].append({"name": ex.exercise_name, "special_logging": ex.special_logging, "setup_notes": ex.setup_notes, "video_link": ex.video_link})
    best_prs = _build_best_prs_for_workouts(db, uid, workouts)
    completions = db.query(WorkoutCompletion).filter(WorkoutCompletion.user_id == uid).all()
    deload = {c.workout_letter: c.completion_count for c in completions}
    last_workout_dates = {}
    for c in completions:
        if c.last_workout_date:
            last_workout_dates[c.workout_letter] = c.last_workout_date.isoformat()
    checkins = db.query(CoreFoodsCheckin).filter(CoreFoodsCheckin.user_id == uid).all()
    core_foods = {c.date: True for c in checkins}
    notes_rows = db.query(UserNote).filter(UserNote.user_id == uid).all()
    notes = {n.exercise: n.note for n in notes_rows}
    swap_rows = db.query(ExerciseSwap).filter(ExerciseSwap.user_id == uid).all()
    swaps = {}
    for s in swap_rows:
        key = f"{s.workout_letter}:{s.exercise_index}"
        swaps[key] = {"original": s.original_exercise, "swapped": s.swapped_exercise}
    now = datetime.utcnow()
    session_rows = db.query(WorkoutSession).filter(WorkoutSession.user_id == uid).all()
    sessions = {}
    for s in session_rows:
        if (now - s.opened_at).total_seconds() < 96 * 3600:
            sessions[s.workout_letter] = {"opened_at": s.opened_at.isoformat(), "log_count": s.log_count}
    # Build session_prs: for each active session, find exercises where the all-time best PR was set during the session window
    session_prs = {}
    for letter, sess_info in sessions.items():
        sess_opened = datetime.fromisoformat(sess_info["opened_at"]) - timedelta(seconds=1)
        sess_end = sess_opened + timedelta(hours=96)
        if letter not in workouts:
            continue
        for idx, ex in enumerate(workouts[letter]):
            ex_name = ex["name"]
            # Check swaps
            swap_key = f"{letter}:{idx}"
            if swap_key in swaps:
                ex_name = swaps[swap_key]["swapped"]
            # Get all PRs for this exercise
            all_prs = db.query(PR).filter(PR.user_id == uid, PR.exercise == ex_name).order_by(PR.estimated_1rm.desc()).all()
            if not all_prs:
                continue
            best = all_prs[0]
            # Was the all-time best set during this session?
            if best.timestamp >= sess_opened and best.timestamp < sess_end:
                # Confirm there was a prior entry (not a first-ever log)
                has_prior = any(p.timestamp < sess_opened for p in all_prs)
                if has_prior:
                    input_key = f"{letter}:{ex_name}:{idx}"
                    session_prs[input_key] = {"w": "BW" if best.weight == 0 else str(int(best.weight)), "r": str(best.reps)}

    # Coach messages
    coach_messages = get_coach_messages_for_user(db, uid)

    # Carousel: check inactivity reset, then build state
    carousel_letters = _get_workout_letters(db, uid)
    check_inactivity_reset(db, uid, carousel_letters)
    carousel = build_carousel_state(db, uid)

    # Strength gains for current cycle
    strength_gains = calculate_strength_gains(db, uid)

    return {"username": member.username, "full_name": member.full_name, "workouts": workouts, "best_prs": best_prs, "deload": deload, "last_workout_dates": last_workout_dates, "core_foods": core_foods, "notes": notes, "swaps": swaps, "sessions": sessions, "session_prs": session_prs, "coach_messages": coach_messages, "carousel": carousel, "strength_gains": strength_gains}


@router.post("/api/weekly-logs", tags=["Weekly Logs"])
def record_weekly_log(user_id: str, message_id: str, xp_awarded: int, db: Session = Depends(get_db)):
    db.add(WeeklyLog(user_id=user_id, message_id=message_id, timestamp=datetime.utcnow(), xp_awarded=xp_awarded))
    db.commit()
    return {"success": True, "xp_awarded": xp_awarded}


@router.get("/api/weekly-logs/{user_id}/can-submit", tags=["Weekly Logs"])
def can_submit_weekly_log(user_id: str, db: Session = Depends(get_db)):
    last_log = db.query(WeeklyLog).filter(WeeklyLog.user_id == user_id).order_by(WeeklyLog.timestamp.desc()).first()
    if not last_log:
        return {"can_submit": True, "days_since_last": None}
    days_since = (datetime.utcnow() - last_log.timestamp).days
    return {"can_submit": days_since >= 6, "days_since_last": days_since}


@router.post("/api/core-foods", tags=["Core Foods"])
def record_core_foods_checkin(user_id: str, message_id: str, xp_awarded: int, date: Optional[str] = None, protein_servings: Optional[int] = None, veggie_servings: Optional[int] = None, db: Session = Depends(get_db)):
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
    existing = db.query(CoreFoodsCheckin).filter(and_(CoreFoodsCheckin.user_id == user_id, CoreFoodsCheckin.date == date)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Already checked in for {date}")
    if protein_servings is not None and (protein_servings < 0 or protein_servings > 4):
        raise HTTPException(status_code=400, detail="Protein servings must be 0-4")
    if veggie_servings is not None and (veggie_servings < 0 or veggie_servings > 3):
        raise HTTPException(status_code=400, detail="Veggie servings must be 0-3")
    checkin = CoreFoodsCheckin(user_id=user_id, date=date, message_id=message_id, timestamp=datetime.utcnow(), xp_awarded=xp_awarded, protein_servings=protein_servings, veggie_servings=veggie_servings)
    db.add(checkin)
    db.commit()
    return {"success": True, "date": date, "days_ago": days_ago, "xp_awarded": xp_awarded, "mode": "learning" if protein_servings is not None else "simple"}


@router.get("/api/core-foods/{user_id}/can-checkin", tags=["Core Foods"])
def can_checkin_core_foods(user_id: str, db: Session = Depends(get_db)):
    today = datetime.utcnow().date().isoformat()
    existing = db.query(CoreFoodsCheckin).filter(and_(CoreFoodsCheckin.user_id == user_id, CoreFoodsCheckin.date == today)).first()
    return {"can_checkin": existing is None}


@router.get("/api/debug/{unique_code}/exercise-names", tags=["Debug"])
def debug_exercise_names(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    all_pr_exercises = db.query(PR.exercise).filter(PR.user_id == member.user_id).distinct().all()
    groups = {}
    for (name,) in all_pr_exercises:
        nk = _normalize_exercise_key(name)
        if nk not in groups:
            groups[nk] = []
        groups[nk].append(name)
    exercises = db.query(Workout).filter(Workout.user_id == member.user_id).all()
    workout_matches = {}
    for ex in exercises:
        matching = _find_all_matching_names(db, member.user_id, ex.exercise_name)
        workout_matches[ex.exercise_name] = {"normalized_key": _normalize_exercise_key(ex.exercise_name), "matched_pr_names": matching}
    return {"pr_name_groups": groups, "workout_plan_matches": workout_matches}


@router.get("/api/admin/config", tags=["Admin"])
def admin_config(key: str = ""):
    ADMIN_KEY = os.environ.get("ADMIN_KEY", "4ifQC_DLzlXM1c5PC6egwvf2p5GgbMR3")
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return {"bot_token": os.environ.get("TTM_BOT_TOKEN", ""), "admin_key": ADMIN_KEY}


@router.get("/api/admin/sql", tags=["Admin"])
def admin_sql(key: str = "", q: str = "", db: Session = Depends(get_db)):
    ADMIN_KEY = os.environ.get("ADMIN_KEY", "4ifQC_DLzlXM1c5PC6egwvf2p5GgbMR3")
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query required")
    if not q.strip().lower().startswith("select"):
        raise HTTPException(status_code=400, detail="Only SELECT queries allowed")
    from sqlalchemy import text
    try:
        result = db.execute(text(q))
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        return {"columns": columns, "rows": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/admin/sql", tags=["Admin"])
def admin_sql_write(key: str = "", q: str = "", db: Session = Depends(get_db)):
    ADMIN_KEY = os.environ.get("ADMIN_KEY", "4ifQC_DLzlXM1c5PC6egwvf2p5GgbMR3")
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query required")
    stmt = q.strip().lower()
    if stmt.startswith("select"):
        raise HTTPException(status_code=400, detail="Use GET for SELECT queries")
    if not (stmt.startswith("update") or stmt.startswith("delete") or stmt.startswith("insert")):
        raise HTTPException(status_code=400, detail="Only UPDATE/DELETE/INSERT allowed")
    from sqlalchemy import text
    try:
        result = db.execute(text(q))
        db.commit()
        return {"success": True, "rows_affected": result.rowcount}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/admin/rescrape", tags=["Admin"])
def admin_rescrape(key: str = "", db: Session = Depends(get_db)):
    import requests as req
    ADMIN_KEY = os.environ.get("ADMIN_KEY", "4ifQC_DLzlXM1c5PC6egwvf2p5GgbMR3")
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    BOT_TOKEN = os.environ.get("TTM_BOT_TOKEN", "")
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TTM_BOT_TOKEN not set")
    CHANNEL_ID = "1459000944028028970"
    MANUAL_USER_IDS = {"919580721922859008", "ND_sonny_a1b2c3d4e5f6"}
    from sqlalchemy import func
    total_before = db.query(func.count(PR.id)).scalar()
    manual_count = db.query(func.count(PR.id)).filter(PR.user_id.in_(MANUAL_USER_IDS)).scalar()
    deleted = db.query(PR).filter(~PR.user_id.in_(MANUAL_USER_IDS)).delete(synchronize_session=False)
    db.commit()
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    all_messages = []
    before = None
    while True:
        params = {"limit": 100}
        if before:
            params["before"] = before
        resp = req.get(f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages", headers=headers, params=params)
        if resp.status_code == 429:
            import time
            time.sleep(resp.json().get("retry_after", 1) + 0.5)
            continue
        if resp.status_code != 200:
            return {"error": f"Discord API returned {resp.status_code}", "deleted": deleted}
        messages = resp.json()
        if not messages:
            break
        all_messages.extend(messages)
        before = messages[-1]["id"]
        if len(messages) < 100:
            break
    from scrape_and_reload import normalize_exercise_name, parse_pr_message
    inserted = 0
    for msg in all_messages:
        author = msg.get("author", {})
        if author.get("bot"):
            continue
        user_id = author.get("id", "")
        username = author.get("username", "unknown")
        content = msg.get("content", "")
        msg_id = msg.get("id", "")
        timestamp_str = msg.get("timestamp", "")
        prs = parse_pr_message(content)
        for pr_data in prs:
            exercise = normalize_exercise_name(pr_data["exercise"])
            if not exercise:
                continue
            weight = pr_data["weight"]
            reps = pr_data["reps"]
            e1rm = calculate_1rm(weight, reps)
            try:
                ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")).replace(tzinfo=None)
            except:
                ts = datetime.utcnow()
            db.add(PR(user_id=user_id, username=username, exercise=exercise, weight=weight, reps=reps, estimated_1rm=e1rm, message_id=msg_id, channel_id=CHANNEL_ID, timestamp=ts))
            inserted += 1
    db.commit()
    total_after = db.query(func.count(PR.id)).scalar()
    return {"status": "success", "before": total_before, "deleted_discord": deleted, "preserved_manual": manual_count, "messages_fetched": len(all_messages), "inserted": inserted, "after": total_after}
