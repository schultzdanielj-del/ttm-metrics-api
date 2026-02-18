"""
TTM Metrics API - Coach Messaging Routes
Two-way text messaging between coach (Dan) and users.
"""

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime
from typing import Optional
import os
import requests as req

from database import get_db, CoachMessage, DashboardMember

router = APIRouter()

COACH_DISCORD_ID = "718992882182258769"
MESSAGE_CAP = 10


def _resolve_member(unique_code: str, db: Session) -> DashboardMember:
    member = db.query(DashboardMember).filter(DashboardMember.unique_code == unique_code).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


def _enforce_message_cap(db: Session, user_id: str):
    """Keep max MESSAGE_CAP messages per user. Delete oldest if over."""
    count = db.query(CoachMessage).filter(CoachMessage.user_id == user_id).count()
    if count >= MESSAGE_CAP:
        excess = count - MESSAGE_CAP + 1
        oldest = db.query(CoachMessage).filter(
            CoachMessage.user_id == user_id
        ).order_by(CoachMessage.created_at.asc()).limit(excess).all()
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
        "audio_duration": msg.audio_duration,
    }


def _send_dm_to_coach(display_name: str, message_text: str):
    """Send a DM to Dan when a user replies from the dashboard."""
    bot_token = os.environ.get("TTM_BOT_TOKEN", "")
    if not bot_token:
        return
    try:
        # Open/get DM channel with coach
        resp = req.post(
            "https://discord.com/api/v10/users/@me/channels",
            headers={"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"},
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
            headers={"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"},
            json={"content": f"**{display_name}**: {message_text}"},
            timeout=5,
        )
    except Exception:
        pass


def get_coach_messages_for_user(db: Session, user_id: str) -> list:
    """Get all coach messages for a user, oldest first. Used by /full endpoint."""
    messages = db.query(CoachMessage).filter(
        CoachMessage.user_id == user_id
    ).order_by(CoachMessage.created_at.asc()).all()
    return [_format_message(m) for m in messages]


# ============================================================================
# Bot → DB: Coach sends a message (from Discord reply)
# ============================================================================

@router.post("/api/coach-messages", tags=["Coach Messages"])
def create_coach_message(body: dict, admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    ADMIN_KEY = os.environ.get("ADMIN_KEY", "4ifQC_DLzlXM1c5PC6egwvf2p5GgbMR3")
    if admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    user_id = body.get("user_id")
    message_text = body.get("message_text")
    discord_msg_id = body.get("discord_msg_id")

    if not user_id or not message_text:
        raise HTTPException(status_code=400, detail="user_id and message_text required")

    db = next(get_db())
    try:
        _enforce_message_cap(db, user_id)
        msg = CoachMessage(
            user_id=user_id,
            message_text=message_text,
            from_coach=True,
            discord_msg_id=discord_msg_id,
            created_at=datetime.utcnow(),
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        return _format_message(msg)
    finally:
        db.close()


# ============================================================================
# Dashboard reads messages
# ============================================================================

@router.get("/api/dashboard/{unique_code}/coach-messages", tags=["Coach Messages"])
def get_coach_messages(unique_code: str, db: Session = Depends(get_db)):
    member = _resolve_member(unique_code, db)
    messages = db.query(CoachMessage).filter(
        CoachMessage.user_id == member.user_id
    ).order_by(CoachMessage.created_at.asc()).all()
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

    _enforce_message_cap(db, member.user_id)
    msg = CoachMessage(
        user_id=member.user_id,
        message_text=message_text,
        from_coach=False,
        created_at=datetime.utcnow(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    # Send DM to Dan
    display_name = member.full_name or member.username or "Someone"
    _send_dm_to_coach(display_name, message_text)

    return _format_message(msg)
