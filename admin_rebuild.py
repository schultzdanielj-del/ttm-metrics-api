"""
Admin endpoint for rebuilding the PRs table from a master dataset.
Import and register with the FastAPI app in main.py.
"""

import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db, PR

router = APIRouter()

ADMIN_KEY = os.getenv("ADMIN_KEY", "4ifQC_DLzlXM1c5PC6egwvf2p5GgbMR3")


def calculate_1rm(weight: float, reps: int) -> float:
    if weight == 0:
        return reps
    return (weight * reps * 0.0333) + weight


@router.post("/api/admin/rebuild-prs", tags=["Admin"])
def admin_rebuild_prs(body: dict, db: Session = Depends(get_db)):
    """
    Wipe ALL PRs and insert a provided master dataset.
    Body: { "key": "<admin_key>", "prs": [ { user_id, username, exercise, weight, reps, estimated_1rm, timestamp, message_id, channel_id }, ... ] }
    """
    if body.get("key") != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    prs_data = body.get("prs", [])
    if not prs_data:
        raise HTTPException(status_code=400, detail="No PRs provided")

    # Count before
    total_before = db.query(func.count(PR.id)).scalar()

    # Wipe all PRs
    db.query(PR).delete(synchronize_session=False)
    db.commit()

    # Insert all provided PRs
    inserted = 0
    for pr_data in prs_data:
        try:
            ts_str = pr_data.get("timestamp", "")
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except:
            ts = datetime.utcnow()

        db.add(PR(
            user_id=pr_data["user_id"],
            username=pr_data["username"],
            exercise=pr_data["exercise"],
            weight=float(pr_data.get("weight", 0)),
            reps=int(pr_data.get("reps", 0)),
            estimated_1rm=float(pr_data.get("estimated_1rm", 0)),
            message_id=pr_data.get("message_id", ""),
            channel_id=pr_data.get("channel_id", ""),
            timestamp=ts,
        ))
        inserted += 1

    db.commit()
    total_after = db.query(func.count(PR.id)).scalar()

    return {
        "status": "success",
        "before": total_before,
        "deleted": total_before,
        "inserted": inserted,
        "after": total_after
    }
