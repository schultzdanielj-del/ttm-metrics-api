"""
One-time backfill script: Populate GameState table from existing PR data.
Also adds total_prs_this_cycle column to cycle_state if missing.

Run once after deploying the new database models.
Safe to run multiple times — skips existing GameState rows.
"""

from sqlalchemy import text, func
from database import SessionLocal, PR, CycleState, GameState, engine, Base


def backfill():
    # Create new tables (GameState) — additive, won't touch existing tables
    Base.metadata.create_all(bind=engine)
    print("Tables created/verified.")

    # Add total_prs_this_cycle column if missing
    with engine.connect() as conn:
        try:
            conn.execute(text(
                "ALTER TABLE cycle_state ADD COLUMN total_prs_this_cycle INTEGER NOT NULL DEFAULT 0"
            ))
            conn.commit()
            print("Added total_prs_this_cycle to cycle_state.")
        except Exception as e:
            conn.rollback()
            if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                print("total_prs_this_cycle already exists, skipping.")
            else:
                print(f"Column add warning: {e}")

    db = SessionLocal()
    try:
        # Get all unique user_id + exercise combinations from PR table
        user_exercises = db.query(
            PR.user_id, PR.exercise
        ).group_by(PR.user_id, PR.exercise).all()

        print(f"Found {len(user_exercises)} user-exercise combinations to backfill.")

        created = 0
        skipped = 0

        for user_id, exercise in user_exercises:
            # Skip if GameState already exists
            existing = db.query(GameState).filter(
                GameState.user_id == user_id,
                GameState.exercise == exercise
            ).first()

            if existing:
                skipped += 1
                continue

            # Get all PRs for this user+exercise, ordered by timestamp
            prs = db.query(PR).filter(
                PR.user_id == user_id,
                PR.exercise == exercise
            ).order_by(PR.timestamp.asc()).all()

            if not prs:
                continue

            first_pr = prs[0]
            floor_e1rm = min(p.estimated_1rm for p in prs)
            work_set_count = len(prs)

            gs = GameState(
                user_id=user_id,
                exercise=exercise,
                charge_up_count=0,  # clean start — no historical grind state
                charge_up_last_updated=None,
                floor_e1rm=floor_e1rm,
                first_e1rm=first_pr.estimated_1rm,
                first_log_date=first_pr.timestamp,
                work_set_count=work_set_count
            )
            db.add(gs)
            created += 1

        # Backfill total_prs_this_cycle for existing users
        cycles = db.query(CycleState).all()
        for cycle in cycles:
            pr_count = db.query(func.count(PR.id)).filter(
                PR.user_id == cycle.user_id,
                PR.timestamp >= cycle.cycle_started_at
            ).scalar()
            cycle.total_prs_this_cycle = pr_count or 0

        db.commit()
        print(f"Backfill complete. Created: {created}, Skipped: {skipped}")
        print(f"Updated total_prs_this_cycle for {len(cycles)} users.")

    finally:
        db.close()


if __name__ == "__main__":
    backfill()
