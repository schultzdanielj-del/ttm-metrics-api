"""
TTM Metrics API - Coach Messaging Routes
Two-way text messaging between coach (Dan) and each dashboard user.
"""

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import asc
from datetime import datetime
import os
import requests as req

from database import get_db, CoachMessage, DashboardMember

router = APIRouter()

COACH_DISCORD_ID = "718992882182258769"


def get_coach_messages_for_user(db: Session, user_id: str) -> list:
    """Called by /full endpoint to include coach messages in dashboard payload."""
    messages = (
        db.query(CoachMessage)
        .filter(CoachMessage.user_id == user_id)
        .order_by(asc(CoachMessage.created_at))
        .all()
    )
    return [_format_message(m) for m in messages]


def _resolve_member(unique_code: str, db: Session) -> DashboardMember:
    member = db.query(DashboardMember).filter(DashboardMember.unique_code == unique_code).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


def _enforce_cap(db: Session, user_id: str, cap: int = 10):
    """Delete oldest messages for user if count exceeds cap."""
    count = db.query(CoachMessage).filter(CoachMessage.user_id == user_id).count()
    if count >= cap:
        overflow = count - cap + 1  # make room for the new one
        oldest = (
            db.query(CoachMessage)
            .filter(CoachMessage.user_id == user_id)
            .order_by(asc(CoachMessage.created_at))
            .limit(overflow)
            .all()
        )
        for msg in oldest:
            db.delete(msg)
        db.flush()


def _format_message(msg: CoachMessage) -> dict:
    return {
        "id": msg.id,
        "user_id": msg.user_id,
        "message_text": msg.message_text,
        "from_coach": msg.from_coach,
        "discord_msg_id": msg.discord_msg_id,
        "created_at": msg.created_at.isoformat(),
    }


def send_dm_to_coach(display_name: str, message_text: str):
    """Send a DM to Dan's Discord when a user replies from the dashboard."""
    token = os.environ.get("TTM_BOT_TOKEN", "")
    if not token:
        return
    try:
        # Open/get DM channel with coach
        resp = req.post(
            "https://discord.com/api/v10/users/@me/channels",
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
            json={"recipient_id": COACH_DISCORD_ID},
            timeout=5,
        )
        if resp.status_code not in (200, 201):
            return
        dm_channel_id = resp.json().get("id")
        if not dm_channel_id:
            return
        # Send the message
        req.post(
            f"https://discord.com/api/v10/channels/{dm_channel_id}/messages",
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
            json={"content": f"**{display_name}**: {message_text}"},
            timeout=5,
        )
    except Exception:
        pass


# ============================================================================
# Bot -> DB: Coach sends a message (called by Discord bot)
# ============================================================================

@router.post("/api/coach-messages", tags=["Coach Messages"])
def create_coach_message(body: dict, x_admin_key: str = Header(None), db: Session = Depends(get_db)):
    ADMIN_KEY = os.environ.get("ADMIN_KEY", "4ifQC_DLzlXM1c5PC6egwvf2p5GgbMR3")
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    user_id = body.get("user_id")
    message_text = body.get("message_text")
    discord_msg_id = body.get("discord_msg_id")

    if not user_id or not message_text:
        raise HTTPException(status_code=400, detail="user_id and message_text required")

    _enforce_cap(db, user_id)
    msg = CoachMessage(
        user_id=user_id,
        message_text=message_text,
        from_coach=True,
        discord_msg_id=discord_msg_id,
        created_at=datetime.utcnow(),
    )
    db.add(msg)
    db.commit()
    return {"status": "created", "id": msg.id}


# ============================================================================
# Dashboard reads coach messages
# ============================================================================

@router.get("/api/dashboard/{unique_code}/coach-messages", tags=["Coach Messages"])
def get_coach_messages(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    messages = (
        db.query(CoachMessage)
        .filter(CoachMessage.user_id == member.user_id)
        .order_by(asc(CoachMessage.created_at))
        .all()
    )
    return [_format_message(m) for m in messages]


# ============================================================================
# User replies from dashboard
# ============================================================================

@router.post("/api/dashboard/{unique_code}/coach-messages/reply", tags=["Coach Messages"])
def reply_to_coach(unique_code: str, body: dict, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    message_text = body.get("message_text", "").strip()
    if not message_text:
        raise HTTPException(status_code=400, detail="message_text required")

    _enforce_cap(db, member.user_id)
    msg = CoachMessage(
        user_id=member.user_id,
        message_text=message_text,
        from_coach=False,
        created_at=datetime.utcnow(),
    )
    db.add(msg)
    db.commit()

    # Send DM to coach
    display_name = member.full_name or member.username or "Someone"
    send_dm_to_coach(display_name, message_text)

    return _format_message(msg)
