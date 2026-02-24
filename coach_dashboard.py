"""
Coach Dashboard API — admin endpoints for group overview, individual member deep-dive,
member creation, and program management.

All endpoints require ADMIN_KEY header for authentication.
"""

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import Optional
import secrets
import os

from database import (
    get_db, PR, Workout, WorkoutCompletion, DashboardMember,
    CoreFoodsCheckin, CycleState, CoachMessage, WorkoutSession,
    ExerciseSwap, UserNote,
)
from carousel import (
    build_carousel_state, calculate_strength_gains,
    _get_workout_letters, _get_completions,
)
from coach_messages import get_coach_messages_for_user

router = APIRouter()


# ============================================================================
# Auth helper
# ============================================================================

def _require_admin(admin_key: str = Header(None, alias="X-Admin-Key")):
    expected = os.environ.get("ADMIN_KEY", "4ifQC_DLzlXM1c5PC6egwvf2p5GgbMR3")
    if not admin_key or admin_key != expected:
        raise HTTPException(status_code=403, detail="Invalid or missing admin key")


# ============================================================================
# GET /api/coach/overview — all members at a glance
# ============================================================================

@router.get("/api/coach/overview", tags=["Coach"])
def coach_overview(db: Session = Depends(get_db), _=Depends(_require_admin)):
    members = db.query(DashboardMember).order_by(DashboardMember.created_at).all()
    now = datetime.utcnow()
    today_str = now.strftime("%Y-%m-%d")

    result = []
    for m in members:
        uid = m.user_id

        # --- Carousel state ---
        cycle_state = db.query(CycleState).filter(CycleState.user_id == uid).first()
        letters = _get_workout_letters(db, uid)
        num_letters = len(letters)
        current_letter = None
        cycle_number = 1
        deload_mode = False
        completions = {}
        if cycle_state and num_letters:
            current_letter = letters[cycle_state.current_position % num_letters]
            cycle_number = cycle_state.cycle_number
            deload_mode = cycle_state.deload_mode
            completions = _get_completions(db, uid, letters)

        # --- Last PR timestamp + days since ---
        latest_pr = db.query(PR).filter(PR.user_id == uid).order_by(PR.timestamp.desc()).first()
        last_pr_at = latest_pr.timestamp.isoformat() + "Z" if latest_pr else None
        days_since_workout = None
        if latest_pr:
            days_since_workout = round((now - latest_pr.timestamp).total_seconds() / 86400, 1)

        # --- PRs this cycle ---
        pr_count_cycle = 0
        if cycle_state:
            pr_count_cycle = db.query(func.count(PR.id)).filter(
                PR.user_id == uid,
                PR.timestamp >= cycle_state.cycle_started_at,
            ).scalar() or 0

        # --- Core foods: streak + today ---
        core_foods_today = db.query(CoreFoodsCheckin).filter(
            CoreFoodsCheckin.user_id == uid,
            CoreFoodsCheckin.date == today_str,
        ).first() is not None

        # Streak: count consecutive days backward from today
        streak = 0
        check_date = now.date()
        while True:
            ds = check_date.strftime("%Y-%m-%d")
            exists = db.query(CoreFoodsCheckin).filter(
                CoreFoodsCheckin.user_id == uid,
                CoreFoodsCheckin.date == ds,
            ).first()
            if exists:
                streak += 1
                check_date -= timedelta(days=1)
            else:
                break

        # --- Strength gains avg ---
        gains = calculate_strength_gains(db, uid)
        avg_strength = gains["avg_change_pct"] if gains else None

        result.append({
            "user_id": uid,
            "username": m.username,
            "full_name": m.full_name,
            "unique_code": m.unique_code,
            "current_letter": current_letter,
            "cycle_number": cycle_number,
            "deload_mode": deload_mode,
            "completions": completions,
            "workout_letters": letters,
            "last_pr_at": last_pr_at,
            "days_since_workout": days_since_workout,
            "pr_count_cycle": pr_count_cycle,
            "core_foods_today": core_foods_today,
            "core_foods_streak": streak,
            "avg_strength_pct": avg_strength,
        })

    return {"members": result, "generated_at": now.isoformat() + "Z"}


# ============================================================================
# GET /api/coach/member/{user_id} — individual deep-dive
# ============================================================================

@router.get("/api/coach/member/{user_id}", tags=["Coach"])
def coach_member_detail(user_id: str, db: Session = Depends(get_db), _=Depends(_require_admin)):
    member = db.query(DashboardMember).filter(DashboardMember.user_id == user_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    uid = member.user_id

    # --- Carousel ---
    carousel = build_carousel_state(db, uid)

    # --- Strength gains ---
    strength_gains = calculate_strength_gains(db, uid)

    # --- Recent PRs (last 30) ---
    recent_prs = db.query(PR).filter(PR.user_id == uid).order_by(PR.timestamp.desc()).limit(30).all()
    pr_list = [{
        "exercise": p.exercise,
        "weight": p.weight,
        "reps": p.reps,
        "estimated_1rm": round(p.estimated_1rm, 1),
        "timestamp": p.timestamp.isoformat() + "Z",
        "source": "dashboard" if p.channel_id == "dashboard" else "discord",
    } for p in recent_prs]

    # --- Core foods last 30 days ---
    thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    checkins = db.query(CoreFoodsCheckin).filter(
        CoreFoodsCheckin.user_id == uid,
        CoreFoodsCheckin.date >= thirty_days_ago,
    ).all()
    core_foods_dates = [c.date for c in checkins]

    # --- Full workout program ---
    exercises = db.query(Workout).filter(Workout.user_id == uid).order_by(
        Workout.workout_letter, Workout.exercise_order
    ).all()
    workouts = {}
    for ex in exercises:
        if ex.workout_letter not in workouts:
            workouts[ex.workout_letter] = []
        workouts[ex.workout_letter].append({
            "name": ex.exercise_name,
            "order": ex.exercise_order,
            "special_logging": ex.special_logging,
            "setup_notes": ex.setup_notes,
            "video_link": ex.video_link,
            "force_bw_protocol": ex.force_bw_protocol,
        })

    # --- Exercise swaps ---
    swap_rows = db.query(ExerciseSwap).filter(ExerciseSwap.user_id == uid).all()
    swaps = {}
    for s in swap_rows:
        key = f"{s.workout_letter}:{s.exercise_index}"
        swaps[key] = {"original": s.original_exercise, "swapped": s.swapped_exercise}

    # --- Coach messages ---
    coach_messages = get_coach_messages_for_user(db, uid)

    # --- Best PRs per exercise ---
    all_pr_exercises = db.query(PR.exercise).filter(PR.user_id == uid).distinct().all()
    best_prs = {}
    for (ex_name,) in all_pr_exercises:
        best = db.query(PR).filter(
            PR.user_id == uid, PR.exercise == ex_name
        ).order_by(PR.estimated_1rm.desc()).first()
        if best:
            best_prs[ex_name] = {
                "weight": best.weight,
                "reps": best.reps,
                "estimated_1rm": round(best.estimated_1rm, 1),
                "timestamp": best.timestamp.isoformat() + "Z",
            }

    return {
        "user_id": uid,
        "username": member.username,
        "full_name": member.full_name,
        "unique_code": member.unique_code,
        "carousel": carousel,
        "strength_gains": strength_gains,
        "recent_prs": pr_list,
        "best_prs": best_prs,
        "core_foods_dates": core_foods_dates,
        "workouts": workouts,
        "swaps": swaps,
        "coach_messages": coach_messages,
    }


# ============================================================================
# POST /api/coach/members — create a new member
# ============================================================================

@router.post("/api/coach/members", tags=["Coach"])
def coach_create_member(body: dict, db: Session = Depends(get_db), _=Depends(_require_admin)):
    full_name = body.get("full_name", "").strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="full_name required")

    discord_id = body.get("discord_id")  # optional
    username = body.get("username", "").strip()  # Discord display name, optional

    # Generate user_id
    if discord_id:
        user_id = str(discord_id)
    else:
        user_id = f"ND_{full_name.split()[0].lower()}_{secrets.token_hex(8)}"

    # Check for existing
    existing = db.query(DashboardMember).filter(DashboardMember.user_id == user_id).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Member already exists with user_id {user_id}")

    # Default username to first name if not provided
    if not username:
        username = full_name.split()[0]

    unique_code = secrets.token_urlsafe(16)
    new_member = DashboardMember(
        user_id=user_id,
        username=username,
        full_name=full_name,
        unique_code=unique_code,
    )
    db.add(new_member)
    db.commit()
    db.refresh(new_member)

    return {
        "user_id": new_member.user_id,
        "username": new_member.username,
        "full_name": new_member.full_name,
        "unique_code": new_member.unique_code,
        "dashboard_url": f"https://dashboard-production-79f2.up.railway.app/{new_member.unique_code}",
    }


# ============================================================================
# PUT /api/coach/members/{user_id}/workouts — replace full program
# ============================================================================

@router.put("/api/coach/members/{user_id}/workouts", tags=["Coach"])
def coach_replace_program(user_id: str, body: dict, db: Session = Depends(get_db), _=Depends(_require_admin)):
    """
    Replace entire workout program atomically.
    Body: { "workouts": { "A": [...], "B": [...], ... } }
    Each exercise: { "name": str, "special_logging"?: str, "setup_notes"?: str,
                     "video_link"?: str, "force_bw_protocol"?: bool }
    """
    member = db.query(DashboardMember).filter(DashboardMember.user_id == user_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    workouts_data = body.get("workouts", {})
    if not workouts_data:
        raise HTTPException(status_code=400, detail="workouts dict required")

    # Delete all existing workouts for this user
    db.query(Workout).filter(Workout.user_id == user_id).delete()

    # Insert new workouts
    total = 0
    for letter in sorted(workouts_data.keys()):
        exercises = workouts_data[letter]
        for idx, ex in enumerate(exercises):
            name = ex.get("name", "").strip()
            if not name:
                continue
            db.add(Workout(
                user_id=user_id,
                workout_letter=letter,
                exercise_order=idx,
                exercise_name=name,
                setup_notes=ex.get("setup_notes"),
                video_link=ex.get("video_link"),
                special_logging=ex.get("special_logging"),
                force_bw_protocol=ex.get("force_bw_protocol", False),
            ))
            total += 1

    # Initialize WorkoutCompletion rows for any new letters
    for letter in sorted(workouts_data.keys()):
        existing_comp = db.query(WorkoutCompletion).filter(
            WorkoutCompletion.user_id == user_id,
            WorkoutCompletion.workout_letter == letter,
        ).first()
        if not existing_comp:
            db.add(WorkoutCompletion(
                user_id=user_id,
                workout_letter=letter,
                completion_count=0,
            ))

    db.commit()
    return {
        "success": True,
        "user_id": user_id,
        "letters": sorted(workouts_data.keys()),
        "total_exercises": total,
    }


# ============================================================================
# PATCH /api/coach/members/{user_id}/workouts/{letter} — update single letter
# ============================================================================

@router.patch("/api/coach/members/{user_id}/workouts/{letter}", tags=["Coach"])
def coach_update_workout_letter(
    user_id: str, letter: str, body: dict,
    db: Session = Depends(get_db), _=Depends(_require_admin)
):
    """
    Replace exercises for a single workout letter.
    Body: { "exercises": [{ "name": str, ... }] }
    """
    member = db.query(DashboardMember).filter(DashboardMember.user_id == user_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    exercises = body.get("exercises", [])
    if not exercises:
        raise HTTPException(status_code=400, detail="exercises array required")

    # Delete existing exercises for this letter
    db.query(Workout).filter(
        Workout.user_id == user_id,
        Workout.workout_letter == letter,
    ).delete()

    # Insert new
    for idx, ex in enumerate(exercises):
        name = ex.get("name", "").strip()
        if not name:
            continue
        db.add(Workout(
            user_id=user_id,
            workout_letter=letter,
            exercise_order=idx,
            exercise_name=name,
            setup_notes=ex.get("setup_notes"),
            video_link=ex.get("video_link"),
            special_logging=ex.get("special_logging"),
            force_bw_protocol=ex.get("force_bw_protocol", False),
        ))

    # Ensure WorkoutCompletion exists
    existing_comp = db.query(WorkoutCompletion).filter(
        WorkoutCompletion.user_id == user_id,
        WorkoutCompletion.workout_letter == letter,
    ).first()
    if not existing_comp:
        db.add(WorkoutCompletion(
            user_id=user_id,
            workout_letter=letter,
            completion_count=0,
        ))

    db.commit()
    return {
        "success": True,
        "user_id": user_id,
        "letter": letter,
        "exercises": len(exercises),
    }


# ============================================================================
# DELETE /api/coach/members/{user_id}/workouts/{letter} — remove a letter
# ============================================================================

@router.delete("/api/coach/members/{user_id}/workouts/{letter}", tags=["Coach"])
def coach_delete_workout_letter(
    user_id: str, letter: str,
    db: Session = Depends(get_db), _=Depends(_require_admin)
):
    member = db.query(DashboardMember).filter(DashboardMember.user_id == user_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    deleted = db.query(Workout).filter(
        Workout.user_id == user_id,
        Workout.workout_letter == letter,
    ).delete()

    # Also clean up WorkoutCompletion for this letter
    db.query(WorkoutCompletion).filter(
        WorkoutCompletion.user_id == user_id,
        WorkoutCompletion.workout_letter == letter,
    ).delete()

    db.commit()
    return {
        "success": True,
        "user_id": user_id,
        "letter": letter,
        "exercises_deleted": deleted,
    }


# ============================================================================
# POST /api/coach/members/{user_id}/cycle-reset — reset cycle manually
# ============================================================================

@router.post("/api/coach/members/{user_id}/cycle-reset", tags=["Coach"])
def coach_reset_cycle(user_id: str, body: dict = {}, db: Session = Depends(get_db), _=Depends(_require_admin)):
    """
    Manually reset a user's cycle. Optionally set position.
    Body: { "position"?: int, "cycle_number"?: int }
    """
    member = db.query(DashboardMember).filter(DashboardMember.user_id == user_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    state = db.query(CycleState).filter(CycleState.user_id == user_id).first()
    now = datetime.utcnow()

    if not state:
        state = CycleState(
            user_id=user_id,
            current_position=body.get("position", 0),
            position_started_at=now,
            deload_mode=False,
            cycle_started_at=now,
            cycle_number=body.get("cycle_number", 1),
        )
        db.add(state)
    else:
        state.current_position = body.get("position", 0)
        state.position_started_at = now
        state.deload_mode = False
        state.cycle_started_at = now
        if "cycle_number" in body:
            state.cycle_number = body["cycle_number"]
        else:
            state.cycle_number += 1

    # Reset completions
    comps = db.query(WorkoutCompletion).filter(WorkoutCompletion.user_id == user_id).all()
    for c in comps:
        c.completion_count = 0
        c.last_workout_date = None

    db.commit()

    carousel = build_carousel_state(db, user_id)
    return {"success": True, "carousel": carousel}


# ============================================================================
# POST /api/coach/members/{user_id}/advance — manually advance carousel
# ============================================================================

@router.post("/api/coach/members/{user_id}/advance", tags=["Coach"])
def coach_advance_carousel(user_id: str, db: Session = Depends(get_db), _=Depends(_require_admin)):
    """Manually advance a user's carousel position (no notifications fired)."""
    member = db.query(DashboardMember).filter(DashboardMember.user_id == user_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    letters = _get_workout_letters(db, user_id)
    if not letters:
        raise HTTPException(status_code=400, detail="No workouts configured")

    state = db.query(CycleState).filter(CycleState.user_id == user_id).first()
    if not state:
        raise HTTPException(status_code=400, detail="No cycle state found")

    state.current_position += 1
    state.position_started_at = datetime.utcnow()
    db.commit()

    carousel = build_carousel_state(db, user_id)
    return {"success": True, "carousel": carousel}
