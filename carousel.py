"""
Carousel system for TTM workout rotation.
Handles cycle state, workout advancement, deload detection, and inactivity resets.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

from database import (
    get_db, CycleState, WorkoutCompletion, Workout, PR, DashboardMember
)
from discord_notifications import (
    post_workout_completion_notification,
    post_deload_notification,
)

router = APIRouter()

COMPLETIONS_PER_LETTER = 6
INACTIVITY_DAYS = 7


# ============================================================================
# Pydantic models
# ============================================================================

class AdvanceRequest(BaseModel):
    reason: str  # "user_advance" or "timer_expiry"


# ============================================================================
# Helper: resolve member from unique_code
# ============================================================================

def _resolve_member(unique_code: str, db: Session) -> DashboardMember:
    member = db.query(DashboardMember).filter(
        DashboardMember.unique_code == unique_code
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


# ============================================================================
# Helper: get sorted workout letters for a user
# ============================================================================

def _get_workout_letters(db: Session, user_id: str) -> list:
    """Return sorted list of distinct workout letters for this user."""
    rows = db.query(Workout.workout_letter).filter(
        Workout.user_id == user_id
    ).distinct().all()
    return sorted([r[0] for r in rows])


# ============================================================================
# Helper: get or create CycleState for a user
# ============================================================================

def _get_or_create_cycle_state(db: Session, user_id: str) -> CycleState:
    state = db.query(CycleState).filter(CycleState.user_id == user_id).first()
    if not state:
        now = datetime.utcnow()
        state = CycleState(
            user_id=user_id,
            current_position=0,
            position_started_at=now,
            deload_mode=False,
            cycle_started_at=now,
            cycle_number=1,
        )
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


# ============================================================================
# Helper: get completions dict for a user
# ============================================================================

def _get_completions(db: Session, user_id: str, letters: list) -> dict:
    """Return {letter: count} for all workout letters, defaulting to 0."""
    rows = db.query(WorkoutCompletion).filter(
        WorkoutCompletion.user_id == user_id
    ).all()
    comp = {r.workout_letter: r.completion_count for r in rows}
    return {letter: comp.get(letter, 0) for letter in letters}


# ============================================================================
# Helper: increment completion count for a letter
# ============================================================================

def _increment_completion(db: Session, user_id: str, letter: str):
    record = db.query(WorkoutCompletion).filter(
        WorkoutCompletion.user_id == user_id,
        WorkoutCompletion.workout_letter == letter,
    ).first()
    if not record:
        record = WorkoutCompletion(
            user_id=user_id,
            workout_letter=letter,
            completion_count=0,
        )
        db.add(record)
    record.completion_count += 1
    record.last_workout_date = datetime.utcnow()


# ============================================================================
# Helper: reset all completion counts for a user
# ============================================================================

def _reset_completions(db: Session, user_id: str):
    rows = db.query(WorkoutCompletion).filter(
        WorkoutCompletion.user_id == user_id
    ).all()
    for r in rows:
        r.completion_count = 0
        r.last_workout_date = None


# ============================================================================
# Helper: calculate strength gains for current cycle
# ============================================================================

def calculate_strength_gains(db: Session, user_id: str) -> dict | None:
    """
    For each exercise with 2+ PR logs in the current cycle,
    compare earliest vs latest estimated_1rm.
    Returns { exercises: [{name, first_1rm, latest_1rm, change_pct}], avg_change_pct }
    or None if no meaningful data.
    """
    state = db.query(CycleState).filter(CycleState.user_id == user_id).first()
    if not state:
        return None

    cycle_start = state.cycle_started_at

    # Get all PRs in current cycle
    cycle_prs = db.query(PR).filter(
        PR.user_id == user_id,
        PR.timestamp >= cycle_start,
    ).order_by(PR.timestamp.asc()).all()

    if not cycle_prs:
        return None

    # Group by exercise
    by_exercise = {}
    for pr in cycle_prs:
        if pr.exercise not in by_exercise:
            by_exercise[pr.exercise] = []
        by_exercise[pr.exercise].append(pr)

    exercises = []
    for ex_name, prs in by_exercise.items():
        if len(prs) < 2:
            continue
        first_1rm = prs[0].estimated_1rm
        latest_1rm = prs[-1].estimated_1rm
        if first_1rm <= 0:
            continue
        change_pct = ((latest_1rm - first_1rm) / first_1rm) * 100
        exercises.append({
            "name": ex_name,
            "first_1rm": round(first_1rm, 1),
            "latest_1rm": round(latest_1rm, 1),
            "change_pct": round(change_pct, 1),
        })

    if not exercises:
        return None

    avg_change = sum(e["change_pct"] for e in exercises) / len(exercises)
    # Sort by change_pct descending (biggest gains first)
    exercises.sort(key=lambda e: e["change_pct"], reverse=True)

    return {
        "exercises": exercises,
        "avg_change_pct": round(avg_change, 1),
    }


# ============================================================================
# Helper: build carousel response object
# ============================================================================

def build_carousel_state(db: Session, user_id: str) -> dict:
    """Build the carousel object returned in /full and /advance responses."""
    letters = _get_workout_letters(db, user_id)
    if not letters:
        return None

    state = _get_or_create_cycle_state(db, user_id)
    num = len(letters)
    completions = _get_completions(db, user_id, letters)

    current_letter = letters[state.current_position % num]

    # Build visible workouts: current + up to 2 previous
    visible = []
    visible.append({
        "letter": current_letter,
        "role": "current",
        "position": state.current_position,
    })
    if state.current_position >= 1:
        prev1_pos = state.current_position - 1
        visible.append({
            "letter": letters[prev1_pos % num],
            "role": "prev1",
            "position": prev1_pos,
        })
    if state.current_position >= 2:
        prev2_pos = state.current_position - 2
        visible.append({
            "letter": letters[prev2_pos % num],
            "role": "prev2",
            "position": prev2_pos,
        })

    return {
        "current_position": state.current_position,
        "current_letter": current_letter,
        "position_started_at": state.position_started_at.isoformat() + "Z",
        "deload_mode": state.deload_mode,
        "cycle_number": state.cycle_number,
        "cycle_started_at": state.cycle_started_at.isoformat() + "Z",
        "completions": completions,
        "workout_letters": letters,
        "visible_workouts": visible,
    }


# ============================================================================
# Helper: 7-day inactivity check
# ============================================================================

def check_inactivity_reset(db: Session, user_id: str, letters: list) -> bool:
    """
    If user has logged at least one PR ever but nothing in the last 7 days,
    treat the absence as a de facto deload and reset the cycle.
    Returns True if a reset was performed.
    """
    if not letters:
        return False

    # Get most recent PR timestamp for this user
    latest_pr = db.query(PR).filter(
        PR.user_id == user_id
    ).order_by(PR.timestamp.desc()).first()

    if not latest_pr:
        # Brand new user, never logged anything — no reset
        return False

    now = datetime.utcnow()
    days_since = (now - latest_pr.timestamp).total_seconds() / 86400

    if days_since < INACTIVITY_DAYS:
        return False

    # User has been inactive 7+ days — reset cycle
    state = _get_or_create_cycle_state(db, user_id)
    num = len(letters)

    # Find which letter the last log was on
    last_letter = None
    last_exercise = latest_pr.exercise
    for letter in letters:
        exercises = db.query(Workout.exercise_name).filter(
            Workout.user_id == user_id,
            Workout.workout_letter == letter,
        ).all()
        ex_names = [e[0] for e in exercises]
        if last_exercise in ex_names:
            last_letter = letter
            break

    # New cycle starts at next letter after last logged workout
    if last_letter and last_letter in letters:
        next_idx = (letters.index(last_letter) + 1) % num
    else:
        next_idx = 0

    state.current_position = next_idx
    state.position_started_at = now
    state.deload_mode = False
    state.cycle_number += 1
    state.cycle_started_at = now
    _reset_completions(db, user_id)
    db.commit()
    return True


# ============================================================================
# Advance endpoint
# ============================================================================

@router.post("/api/dashboard/{unique_code}/advance", tags=["Dashboard"])
def advance_carousel(unique_code: str, req: AdvanceRequest, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    uid = member.user_id
    letters = _get_workout_letters(db, uid)

    if not letters:
        raise HTTPException(status_code=400, detail="No workouts configured for this user")

    num = len(letters)
    state = _get_or_create_cycle_state(db, uid)
    current_letter = letters[state.current_position % num]
    now = datetime.utcnow()

    # Track what happened for notifications
    completed_letter = current_letter
    entered_deload = False
    cycle_reset = False

    if not state.deload_mode:
        # Normal mode: increment completion for current letter
        _increment_completion(db, uid, current_letter)

        # Check if all letters hit the target
        completions = _get_completions(db, uid, letters)
        all_complete = all(completions[l] >= COMPLETIONS_PER_LETTER for l in letters)
        if all_complete:
            state.deload_mode = True
            entered_deload = True
            # Reset completions — they'll be used to track deload passes
            _reset_completions(db, uid)
            db.commit()
    else:
        # Deload mode: mark current letter as done (completion = 1 means done)
        _increment_completion(db, uid, current_letter)

        # Check if all deload letters are done (each has 1 completion)
        completions = _get_completions(db, uid, letters)
        all_deload_done = all(completions[l] >= 1 for l in letters)
        if all_deload_done:
            # Deload complete — new cycle
            state.deload_mode = False
            state.cycle_number += 1
            state.cycle_started_at = now
            cycle_reset = True
            _reset_completions(db, uid)
            # Position resets to 0 (will be set below after advance)
            # Actually we want next position to be 0, so set to -1 before the +1 below
            state.current_position = -1
            db.commit()

    # Save session start time before advancing (needed for clean sweep check)
    completed_position_started = state.position_started_at

    # Advance position
    state.current_position += 1
    state.position_started_at = now
    db.commit()

    # Fire Discord notifications (fire-and-forget, failures don't affect response)
    try:
        if entered_deload:
            # The advance that completed the cycle — check for clean sweep + deload notification
            post_workout_completion_notification(db, uid, completed_letter, position_started_at=completed_position_started)
            # Calculate strength gains for the deload notification
            gains = calculate_strength_gains(db, uid)
            avg_pct = gains["avg_change_pct"] if gains else None
            post_deload_notification(db, uid, strength_pct=avg_pct)
        elif not state.deload_mode and not cycle_reset:
            # Normal advance — check for clean sweep only
            post_workout_completion_notification(db, uid, completed_letter, position_started_at=completed_position_started)
        # During deload advances or cycle reset advance: no notification
    except Exception:
        pass  # Notifications are best-effort

    carousel = build_carousel_state(db, uid)
    return {
        "success": True,
        "reason": req.reason,
        "carousel": carousel,
        "entered_deload": entered_deload,
        "cycle_reset": cycle_reset,
    }


# ============================================================================
# Go back endpoint
# ============================================================================

@router.post("/api/dashboard/{unique_code}/go-back", tags=["Dashboard"])
def go_back_carousel(unique_code: str, db: Session = Depends(get_db)):
    """Move carousel back one position. Undoes the last advance."""
    member = _resolve_member(unique_code, db)
    uid = member.user_id
    letters = _get_workout_letters(db, uid)

    if not letters:
        raise HTTPException(status_code=400, detail="No workouts configured")

    state = _get_or_create_cycle_state(db, uid)

    if state.current_position <= 0:
        raise HTTPException(status_code=400, detail="Already at the beginning")

    num = len(letters)

    # The letter we're leaving (current) — decrement its completion if we
    # previously counted it. Actually, the completion was recorded for the
    # letter we ADVANCED FROM, not the current one. When we advanced from
    # position N to N+1, position N's letter got a completion bump.
    # Going back means we undo that: decrement the letter at position N
    # (which is position current_position - 1 after the advance, i.e. the
    # letter we're going BACK to).
    prev_position = state.current_position - 1
    prev_letter = letters[prev_position % num]

    # Decrement completion for that letter
    record = db.query(WorkoutCompletion).filter(
        WorkoutCompletion.user_id == uid,
        WorkoutCompletion.workout_letter == prev_letter,
    ).first()
    if record and record.completion_count > 0:
        record.completion_count -= 1

    # If we were in deload and going back, exit deload
    if state.deload_mode:
        state.deload_mode = False

    state.current_position = prev_position
    state.position_started_at = datetime.utcnow()
    db.commit()

    carousel = build_carousel_state(db, uid)
    return {"success": True, "carousel": carousel}
