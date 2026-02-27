"""
TTM Game Engine — Gamification layer logic
All game behavior detection, state management, and reframe generation.
Server-side only. Dashboard receives computed state and renders it.

This file is NOT wired into any routes yet. It will be integrated
when the new dashboard is ready to consume game state.
"""

from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import PR, CycleState, CoreFoodsCheckin, WorkoutSession, GameState


# ============================================================================
# Configurable Thresholds
# ============================================================================

CHARGE_UP_THRESHOLD = 0.85       # % of best e1RM to qualify as "grinding near best"
CHARGE_UP_MAX = 5                # maximum pressure segments
BAD_DAY_THRESHOLD = 0.80         # % of best e1RM — below this counts toward "bad day"
BAD_DAY_MIN_EXERCISES = 2        # minimum exercises below threshold to detect a bad day
ANOMALY_THRESHOLD = 0.25         # % improvement that triggers anomaly dampening
STAGE_2_MIN_CYCLES = 2           # completed cycles to enter stage 2
STAGE_2_MIN_CF_DAYS = 5          # core food days to enter stage 2 (alternative path)
STAGE_3_MIN_CYCLES = 3           # completed cycles to enter stage 3
CHARGEUP_MIN_WORK_SETS = 8      # minimum work sets before charge-up activates
HIGHER_LOW_MIN_WORK_SETS = 10   # minimum work sets before higher-low activates
PR_MAGNITUDE_MIN_WORK_SETS = 3  # minimum work sets before magnitude scaling activates
DISRUPTION_GAP_DAYS = 7          # days of no workout to trigger return-from-disruption
MILESTONE_THRESHOLDS = [0.25, 0.50, 1.00]  # aggregate strength improvement thresholds


# ============================================================================
# Reframe Copy
# ============================================================================

REFRAME_COPY = {
    "R1":         ["Pressure building.", "Spring loading.", "Body adapting. PR incoming."],
    "R1_release": ["Pressure released.", "That's what grinding builds.", "Spring unloaded."],
    "R3":         ["Floor raised.", "Higher low. That counts.", "Net gain on a tough day."],
    "R4":         ["Fresh cycle. 6 ahead.", "Break was the deload. Reloaded.", "Picking up where you left off."],
    "R7":         ["Core foods held through the gap. Still in the game.", "Didn't train. Still ate right. That's a win."],
    "R6":         ["Maximum pressure built. Body catches up now.", "Strategic rest. Come back stronger.", "Cycle complete. Recovery earns the next round."],
    "R13":        ["Freebies are done. Building permanent changes now.", "Slower but compounding. This is the real game."],
    "R14":        ["Different equipment. Same work. Counts.", "Subbed in. Train to failure. It counts."],
    # R2, R5 are shown in cycle summary / journey arc context only
    "R2":         ["Fewer PRs per cycle is normal. Each one is bigger.", "5% per cycle. Doubles in a year.", "Compounding. Every cycle stacks."],
    "R5":         ["This rotates. Other lifts are proving it works.", "Stagnant now. Will break. Keep pushing."],
}


# ============================================================================
# Stage Detection
# ============================================================================

def compute_stage(db: Session, user_id: str) -> int:
    """Determine which gating stage the user is in (1, 2, or 3)."""
    cycle = db.query(CycleState).filter(CycleState.user_id == user_id).first()

    # Stage 3: 3+ completed cycles
    if cycle and cycle.cycle_number >= 3:
        return 3

    # Stage 2: 2+ cycles OR 5+ core food days
    cf_count = db.query(func.count(CoreFoodsCheckin.id)).filter(
        CoreFoodsCheckin.user_id == user_id
    ).scalar()
    if (cycle and cycle.cycle_number >= 2) or cf_count >= STAGE_2_MIN_CF_DAYS:
        return 2

    return 1


# ============================================================================
# Charge-Up Logic
# ============================================================================

def update_charge_up(db: Session, user_id: str, exercise: str,
                     estimated_1rm: float, is_pr: bool, best_e1rm: float | None) -> dict | None:
    """
    Update charge-up state after a log. Returns game update dict or None.
    Called from dashboard_log_exercise after PR determination.
    """
    gs = db.query(GameState).filter(
        GameState.user_id == user_id,
        GameState.exercise == exercise
    ).first()

    if not gs:
        return None

    if gs.work_set_count < CHARGEUP_MIN_WORK_SETS:
        return None

    if is_pr:
        released_count = gs.charge_up_count
        gs.charge_up_count = 0
        gs.charge_up_last_updated = datetime.utcnow()
        if released_count > 0:
            return {
                "charge_up_released": True,
                "charge_up_released_count": released_count
            }
        return None

    if best_e1rm and best_e1rm > 0 and estimated_1rm > 0:
        ratio = estimated_1rm / best_e1rm
        if ratio >= CHARGE_UP_THRESHOLD:
            gs.charge_up_count = min(gs.charge_up_count + 1, CHARGE_UP_MAX)
            gs.charge_up_last_updated = datetime.utcnow()
            return {
                "charge_up_released": False,
                "charge_up": gs.charge_up_count
            }

    return None  # below threshold — no charge-up activity


def check_charge_up_decay(db: Session, user_id: str):
    """Reset charge-up if cycle reset happened after last charge event."""
    cycle = db.query(CycleState).filter(CycleState.user_id == user_id).first()
    if not cycle:
        return

    game_states = db.query(GameState).filter(
        GameState.user_id == user_id,
        GameState.charge_up_count > 0
    ).all()

    for gs in game_states:
        if gs.charge_up_last_updated and cycle.cycle_started_at > gs.charge_up_last_updated:
            gs.charge_up_count = 0


# ============================================================================
# Bad Day / Higher-Low Detection
# ============================================================================

def detect_bad_day(session_logs: list, best_e1rms: dict) -> bool:
    """
    Check if multiple exercises in current session are significantly below best.
    session_logs: list of dicts with {exercise, estimated_1rm}
    best_e1rms: dict keyed by exercise name → best e1rm float value
    """
    below_count = 0
    for log in session_logs:
        best = best_e1rms.get(log["exercise"])
        if not best or best <= 0:
            continue
        ratio = log["estimated_1rm"] / best
        if ratio < BAD_DAY_THRESHOLD:
            below_count += 1
    return below_count >= BAD_DAY_MIN_EXERCISES


def check_higher_low(estimated_1rm: float, floor_e1rm: float | None,
                     bad_day_detected: bool) -> bool:
    """Check if a set on a bad day is above the historical floor."""
    if not bad_day_detected or not floor_e1rm or floor_e1rm <= 0:
        return False
    return estimated_1rm > floor_e1rm


# ============================================================================
# Anomaly Detection
# ============================================================================

def check_anomaly(new_e1rm: float, previous_best_e1rm: float | None) -> bool:
    """Flag suspicious 25%+ e1RM jumps."""
    if not previous_best_e1rm or previous_best_e1rm <= 0:
        return False
    improvement = (new_e1rm - previous_best_e1rm) / previous_best_e1rm
    return improvement > ANOMALY_THRESHOLD


def compute_pr_magnitude_pct(new_e1rm: float, previous_best_e1rm: float | None) -> float | None:
    """Calculate e1RM improvement percentage for PR magnitude scaling."""
    if not previous_best_e1rm or previous_best_e1rm <= 0:
        return None
    return ((new_e1rm - previous_best_e1rm) / previous_best_e1rm) * 100


# ============================================================================
# Return-From-Disruption Detection
# ============================================================================

def detect_return_from_disruption(db: Session, user_id: str) -> tuple[bool, bool]:
    """
    Check if user is returning from a 7+ day workout gap.
    Returns (is_returning, core_foods_during_gap).
    """
    latest_session = db.query(WorkoutSession).filter(
        WorkoutSession.user_id == user_id
    ).order_by(WorkoutSession.opened_at.desc()).first()

    if not latest_session:
        return False, False

    gap_days = (datetime.utcnow() - latest_session.opened_at).days
    if gap_days < DISRUPTION_GAP_DAYS:
        return False, False

    # Check if core foods were logged during the gap
    gap_start = latest_session.opened_at.date().isoformat()
    gap_end = datetime.utcnow().date().isoformat()
    cf_during_gap = db.query(CoreFoodsCheckin).filter(
        CoreFoodsCheckin.user_id == user_id,
        CoreFoodsCheckin.date >= gap_start,
        CoreFoodsCheckin.date <= gap_end
    ).count() > 0

    return True, cf_during_gap


# ============================================================================
# GameState Management
# ============================================================================

def get_or_create_game_state(db: Session, user_id: str, exercise: str) -> GameState:
    """Get existing GameState or create a new one."""
    gs = db.query(GameState).filter(
        GameState.user_id == user_id,
        GameState.exercise == exercise
    ).first()

    if not gs:
        gs = GameState(
            user_id=user_id,
            exercise=exercise,
            charge_up_count=0,
            work_set_count=0
        )
        db.add(gs)
        db.flush()

    return gs


def update_game_state_on_log(db: Session, user_id: str, exercise: str,
                             estimated_1rm: float, is_pr: bool,
                             best_e1rm: float | None) -> dict:
    """
    Update all GameState fields after a log. Returns game update dict
    to include in log response.
    """
    gs = get_or_create_game_state(db, user_id, exercise)

    # Increment work set count
    gs.work_set_count += 1

    # Set first e1rm if this is the first log
    if gs.first_e1rm is None:
        gs.first_e1rm = estimated_1rm
        gs.first_log_date = datetime.utcnow()

    # Update floor (historical worst)
    if gs.floor_e1rm is None or estimated_1rm < gs.floor_e1rm:
        gs.floor_e1rm = estimated_1rm

    # PR magnitude
    pr_magnitude_pct = None
    is_anomaly = False
    if is_pr and gs.work_set_count >= PR_MAGNITUDE_MIN_WORK_SETS:
        pr_magnitude_pct = compute_pr_magnitude_pct(estimated_1rm, best_e1rm)
        is_anomaly = check_anomaly(estimated_1rm, best_e1rm)

    # Charge-up
    charge_up_result = update_charge_up(db, user_id, exercise, estimated_1rm, is_pr, best_e1rm)

    # Higher-low detection (bad day + above floor)
    higher_low = False
    if not is_pr and gs.work_set_count >= HIGHER_LOW_MIN_WORK_SETS and gs.floor_e1rm:
        # Check if this is a bad day by looking at current session's logs
        latest_session = db.query(WorkoutSession).filter(
            WorkoutSession.user_id == user_id
        ).order_by(WorkoutSession.opened_at.desc()).first()

        if latest_session:
            session_prs = db.query(PR).filter(
                PR.user_id == user_id,
                PR.timestamp >= latest_session.opened_at,
            ).all()

            if len(session_prs) >= 2:
                # Build best_e1rms dict
                best_e1rms = {}
                for spr in session_prs:
                    if spr.exercise not in best_e1rms:
                        best = db.query(func.max(PR.estimated_1rm)).filter(
                            PR.user_id == user_id,
                            PR.exercise == spr.exercise
                        ).scalar()
                        best_e1rms[spr.exercise] = best or 0

                session_logs = [{"exercise": spr.exercise, "estimated_1rm": spr.estimated_1rm} for spr in session_prs]
                is_bad_day = detect_bad_day(session_logs, best_e1rms)
                if is_bad_day:
                    higher_low = check_higher_low(estimated_1rm, gs.floor_e1rm, True)

    # Build response
    game_update = {
        "charge_up": gs.charge_up_count,
        "pr_magnitude_pct": round(pr_magnitude_pct, 1) if pr_magnitude_pct is not None else None,
        "is_anomaly": is_anomaly,
        "charge_up_released": False,
        "charge_up_released_count": 0,
        "higher_low": higher_low,
    }

    if charge_up_result:
        game_update.update(charge_up_result)

    return game_update


# ============================================================================
# Reframe Engine
# ============================================================================

def _select_variant(reframe_type: str, exercise: str | None = None) -> int:
    """Deterministic variant selection: same type+exercise+day = same variant."""
    key = f"{reframe_type}:{exercise or ''}:{date.today().isoformat()}"
    variants = REFRAME_COPY.get(reframe_type, [])
    if not variants:
        return 0
    return hash(key) % len(variants)


def build_reframe(reframe_type: str, location: str, exercise: str | None = None) -> dict:
    """Build a reframe dict for API response."""
    variants = REFRAME_COPY.get(reframe_type, [])
    if not variants:
        return None
    idx = _select_variant(reframe_type, exercise)
    return {
        "type": reframe_type,
        "location": location,
        "exercise": exercise,
        "variant": idx,
        "text": variants[idx]
    }


def compute_reframes(stage: int, exercises_game_state: dict,
                     return_from_disruption: bool, core_foods_during_gap: bool,
                     bad_day_detected: bool, deload_mode: bool,
                     swapped_exercises: list | None = None,
                     cycle_summary: dict | None = None) -> list:
    """
    Compute all active reframes for the current state.
    Returns list of reframe dicts for the API response.
    """
    reframes = []

    # Return-from-disruption and deload reframes available at all stages
    if return_from_disruption:
        rf = build_reframe("R4", "workout_header")
        if rf:
            reframes.append(rf)
        if core_foods_during_gap:
            rf = build_reframe("R7", "core_foods")
            if rf:
                reframes.append(rf)

    if deload_mode:
        rf = build_reframe("R6", "deload_card")
        if rf:
            reframes.append(rf)

        # R2: PR frequency dropping (cycle 3+, fewer PRs than previous)
        if cycle_summary and stage >= 3:
            cs = cycle_summary
            prev = cs.get("previous_cycle")
            if cs.get("cycle_number", 0) >= 3 and prev:
                if cs.get("total_prs", 0) < prev.get("total_prs", 0):
                    rf = build_reframe("R2", "cycle_summary")
                    if rf:
                        reframes.append(rf)

            # R13: Slow progress after fast phase (cycle 3+, avg change < 5%)
            if cs.get("cycle_number", 0) >= 3:
                avg = cs.get("avg_strength_change_pct", 0)
                if 0 < avg < 5:
                    rf = build_reframe("R13", "cycle_summary")
                    if rf:
                        reframes.append(rf)

    if stage < 3:
        return reframes

    # Stage 3+ — full reframe engine
    for ex_name, gs in exercises_game_state.items():
        if gs.charge_up_count > 0 and gs.work_set_count >= CHARGEUP_MIN_WORK_SETS:
            rf = build_reframe("R1", "exercise", exercise=ex_name)
            if rf:
                reframes.append(rf)

    if bad_day_detected:
        rf = build_reframe("R3", "workout_header")
        if rf:
            reframes.append(rf)

    if swapped_exercises:
        for swap_ex in swapped_exercises:
            rf = build_reframe("R14", "exercise", exercise=swap_ex)
            if rf:
                reframes.append(rf)

    return reframes


# ============================================================================
# Journey Arc Data
# ============================================================================

def compute_journey_data(db: Session, user_id: str, stage: int) -> dict | None:
    """
    Compute journey arc data for /full response.
    Returns summary-level data. Full history served by /journey endpoint.
    """
    if stage < 2:
        return None

    game_states = db.query(GameState).filter(
        GameState.user_id == user_id,
        GameState.first_e1rm.isnot(None)
    ).all()

    if not game_states:
        return None

    # Aggregate: sum of first e1rms vs sum of best e1rms
    total_first = 0
    total_best = 0
    for gs in game_states:
        if gs.first_e1rm and gs.first_e1rm > 0:
            total_first += gs.first_e1rm
            # Get current best for this exercise
            best = db.query(func.max(PR.estimated_1rm)).filter(
                PR.user_id == user_id,
                PR.exercise == gs.exercise
            ).scalar()
            if best:
                total_best += best

    if total_first <= 0:
        return None

    total_change_pct = ((total_best - total_first) / total_first) * 100

    # Check milestones
    milestone_crossed = None
    ratio = total_best / total_first - 1 if total_first > 0 else 0
    for threshold in MILESTONE_THRESHOLDS:
        if ratio >= threshold:
            milestone_crossed = f"{int(threshold * 100)}%"

    # Cycle history
    cycle = db.query(CycleState).filter(CycleState.user_id == user_id).first()
    cycles_completed = (cycle.cycle_number - 1) if cycle else 0

    # Compounding total
    # Get per-cycle avg strength change from PR data
    cycle_history = _compute_cycle_history(db, user_id, cycle) if cycle and cycles_completed > 0 else []

    compounding_total = 1.0
    for ch in cycle_history:
        compounding_total *= (1 + ch["avg_change_pct"] / 100)
    compounding_total_pct = (compounding_total - 1) * 100

    return {
        "total_first_e1rm": round(total_first, 1),
        "total_best_e1rm": round(total_best, 1),
        "total_change_pct": round(total_change_pct, 1),
        "milestone_crossed": milestone_crossed,
        "cycles_completed": cycles_completed,
        "cycle_history": cycle_history,
        "compounding_total_pct": round(compounding_total_pct, 1)
    }


def _compute_cycle_history(db: Session, user_id: str, cycle_state: CycleState) -> list:
    """
    Derive per-cycle stats from PR data and cycle boundaries.
    This is approximate — we use cycle_started_at and work backwards.
    For more accuracy, we'd need to store cycle boundaries explicitly.
    """
    # For now, return empty — this will be refined when we have
    # explicit cycle boundary tracking. The current CycleState only
    # stores the CURRENT cycle's start, not historical boundaries.
    # TODO: When building the journey endpoint, derive boundaries from
    # WorkoutCompletion timestamps or add a CycleHistory table.
    return []


# ============================================================================
# Full Game State for /full Response
# ============================================================================

def compute_cycle_summary(db: Session, user_id: str) -> dict | None:
    """
    Compute cycle summary for display during deload.
    Includes: total PRs, avg strength change, previous cycle comparison,
    compounding total since day 1, and milestone detection.
    """
    cycle = db.query(CycleState).filter(CycleState.user_id == user_id).first()
    if not cycle:
        return None

    cycle_num = cycle.cycle_number if hasattr(cycle, 'cycle_number') else 1
    total_prs = cycle.total_prs_this_cycle if hasattr(cycle, 'total_prs_this_cycle') else 0

    # Current cycle strength change — PRs logged since cycle_started_at
    cycle_start = cycle.cycle_started_at
    cycle_prs = db.query(PR).filter(
        PR.user_id == user_id,
        PR.timestamp >= cycle_start,
    ).order_by(PR.timestamp.asc()).all()

    # Group by exercise, calc per-exercise change
    by_exercise = {}
    for pr in cycle_prs:
        if pr.exercise not in by_exercise:
            by_exercise[pr.exercise] = []
        by_exercise[pr.exercise].append(pr)

    ex_changes = []
    for ex_name, prs in by_exercise.items():
        if len(prs) < 2:
            continue
        first_1rm = prs[0].estimated_1rm
        latest_1rm = prs[-1].estimated_1rm
        if first_1rm and first_1rm > 0:
            change_pct = ((latest_1rm - first_1rm) / first_1rm) * 100
            ex_changes.append(change_pct)

    avg_strength_change = round(sum(ex_changes) / len(ex_changes), 1) if ex_changes else 0.0

    # Previous cycle comparison (if cycle 2+)
    previous_cycle = None
    if cycle_num >= 2:
        # Find PRs from the previous cycle by looking at PRs before current cycle start
        # and after the cycle before that
        prev_prs = db.query(PR).filter(
            PR.user_id == user_id,
            PR.timestamp < cycle_start,
        ).order_by(PR.timestamp.desc()).all()

        if prev_prs:
            previous_cycle = {
                "total_prs": len(prev_prs),  # rough — all PRs before this cycle
                "cycle_number": cycle_num - 1,
            }

    # Compounding total since day 1 (if cycle 3+)
    compounding_total_pct = None
    all_gs = db.query(GameState).filter(GameState.user_id == user_id).all()
    total_first = sum(gs.first_e1rm for gs in all_gs if gs.first_e1rm)
    if total_first > 0:
        # Get current best e1RM per exercise
        total_best = 0.0
        for gs in all_gs:
            best = db.query(func.max(PR.estimated_1rm)).filter(
                PR.user_id == user_id,
                PR.exercise == gs.exercise
            ).scalar()
            if best:
                total_best += best
        if total_best > total_first:
            compounding_total_pct = round(((total_best - total_first) / total_first) * 100, 1)

    # Milestone detection
    milestone = None
    if compounding_total_pct is not None:
        for threshold in [100, 50, 25]:
            if compounding_total_pct >= threshold:
                milestone = threshold
                break

    return {
        "total_prs": total_prs,
        "avg_strength_change_pct": avg_strength_change,
        "cycle_number": cycle_num,
        "previous_cycle": previous_cycle,
        "compounding_total_pct": compounding_total_pct,
        "milestone": milestone,
    }


def compute_game_state(db: Session, user_id: str, workouts: dict,
                       sessions: dict, swaps: dict,
                       deload_mode: bool) -> dict:
    """
    Compute the complete game state dict for the /full API response.
    This is the main entry point called from get_full_dashboard().
    """
    stage = compute_stage(db, user_id)

    # Check charge-up decay
    check_charge_up_decay(db, user_id)

    # Get all game states for this user
    all_gs = db.query(GameState).filter(GameState.user_id == user_id).all()
    gs_by_exercise = {gs.exercise: gs for gs in all_gs}

    # Build per-exercise game data
    exercises_game = {}
    for gs in all_gs:
        # Get current best e1rm
        best_e1rm = db.query(func.max(PR.estimated_1rm)).filter(
            PR.user_id == user_id,
            PR.exercise == gs.exercise
        ).scalar()

        exercises_game[gs.exercise] = {
            "charge_up": gs.charge_up_count if stage >= 3 else 0,
            "floor_e1rm": round(gs.floor_e1rm, 1) if gs.floor_e1rm else None,
            "first_e1rm": round(gs.first_e1rm, 1) if gs.first_e1rm else None,
            "first_log_date": gs.first_log_date.isoformat() if gs.first_log_date else None,
            "best_e1rm": round(best_e1rm, 1) if best_e1rm else None,
            "work_set_count": gs.work_set_count,
        }

    # Detect return from disruption
    is_returning, cf_during_gap = detect_return_from_disruption(db, user_id)

    # Detect bad day from current session logs
    bad_day = False
    bad_day_higher_lows = {}  # exercise → True if higher-low on bad day
    if sessions:
        # Find the most recent active session
        latest_letter = None
        latest_opened = None
        for letter, sess_info in sessions.items():
            opened = sess_info.get("opened_at", "")
            if not latest_opened or opened > latest_opened:
                latest_opened = opened
                latest_letter = letter

        if latest_letter and latest_opened:
            # Get PRs logged in this session
            sess_start = datetime.fromisoformat(latest_opened)
            session_prs = db.query(PR).filter(
                PR.user_id == user_id,
                PR.timestamp >= sess_start,
            ).all()

            if session_prs:
                # Build best_e1rms dict from exercises_game
                best_e1rms = {ex: data.get("best_e1rm", 0) or 0 for ex, data in exercises_game.items()}
                session_logs = [{"exercise": pr.exercise, "estimated_1rm": pr.estimated_1rm} for pr in session_prs]

                bad_day = detect_bad_day(session_logs, best_e1rms)

                # If bad day detected, check higher-low per exercise
                if bad_day and stage >= 3:
                    for log in session_logs:
                        gs = gs_by_exercise.get(log["exercise"])
                        if gs and gs.work_set_count >= HIGHER_LOW_MIN_WORK_SETS:
                            if check_higher_low(log["estimated_1rm"], gs.floor_e1rm, True):
                                bad_day_higher_lows[log["exercise"]] = True

    # Add higher-low flags to per-exercise game data
    for ex_name in exercises_game:
        exercises_game[ex_name]["higher_low"] = bad_day_higher_lows.get(ex_name, False)

    # Collect swapped exercises
    swapped_exercises = []
    for key, swap_info in swaps.items():
        if isinstance(swap_info, dict) and "swapped" in swap_info:
            swapped_exercises.append(swap_info["swapped"])
        elif isinstance(swap_info, str):
            swapped_exercises.append(swap_info)

    # Cycle summary (populated when deload is active) — computed before reframes since R2/R13 need it
    cycle_summary = None
    if deload_mode:
        cycle_summary = compute_cycle_summary(db, user_id)

    # Compute reframes
    reframes = compute_reframes(
        stage=stage,
        exercises_game_state={k: gs_by_exercise[k] for k in gs_by_exercise if k in exercises_game},
        return_from_disruption=is_returning,
        core_foods_during_gap=cf_during_gap,
        bad_day_detected=bad_day,
        deload_mode=deload_mode,
        swapped_exercises=swapped_exercises if stage >= 3 else None,
        cycle_summary=cycle_summary
    )

    # Journey data
    journey = compute_journey_data(db, user_id, stage)

    return {
        "stage": stage,
        "exercises": exercises_game,
        "reframes": reframes,
        "journey": journey,
        "cycle_summary": cycle_summary,
        "return_from_disruption": is_returning,
        "core_foods_during_gap": cf_during_gap,
        "bad_day_detected": bad_day,
    }
