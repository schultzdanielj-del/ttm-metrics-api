"""
Discord Notifications for TTM Dashboard Actions
Posts to #pr-city channel via Discord REST API using bot token.
"""

import os
import requests
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database import DashboardMember, Workout, PR

CHANNEL_ID = "1459000944028028970"


def _get_bot_token():
    return os.environ.get("TTM_BOT_TOKEN", "")


def _get_bot_user_id():
    """Get the bot's own user ID for filtering messages."""
    token = _get_bot_token()
    if not token:
        return None
    try:
        resp = requests.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {token}"},
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json().get("id")
    except Exception:
        pass
    return None


def _get_display_name(db: Session, user_id: str) -> str:
    """Get Discord display name from DashboardMembers. Falls back to full_name."""
    member = db.query(DashboardMember).filter(DashboardMember.user_id == user_id).first()
    if not member:
        return "Someone"
    return member.username or member.full_name or "Someone"


def _get_time_ref(date_str: str) -> str:
    """Convert date string to relative time reference in EST."""
    try:
        target = datetime.fromisoformat(date_str).date()
    except (ValueError, TypeError):
        return "today"
    # Approximate EST as UTC-5
    now_est = datetime.utcnow() - timedelta(hours=5)
    today_est = now_est.date()
    diff = (today_est - target).days
    if diff == 0:
        return "today"
    elif diff == 1:
        return "yesterday"
    else:
        return target.strftime("%A")  # day name


def _post_message(content: str) -> str | None:
    """Post a message to #pr-city. Returns message ID on success, None on failure."""
    token = _get_bot_token()
    if not token:
        return None
    try:
        resp = requests.post(
            f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages",
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
            json={"content": content},
            timeout=5,
        )
        if resp.status_code in (200, 201):
            return resp.json().get("id")
    except Exception:
        pass
    return None


def _react_to_message(message_id: str, emoji: str):
    """Add a reaction to a message in #pr-city."""
    token = _get_bot_token()
    if not token or not message_id:
        return
    try:
        requests.put(
            f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages/{message_id}/reactions/{emoji}/@me",
            headers={"Authorization": f"Bot {token}"},
            timeout=5,
        )
    except Exception:
        pass


def _find_and_delete_bot_message(display_name: str, match_text: str):
    """Search last 100 messages for a bot message containing display_name and match_text, then delete it."""
    token = _get_bot_token()
    if not token:
        return
    bot_id = _get_bot_user_id()
    if not bot_id:
        return
    try:
        resp = requests.get(
            f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages",
            headers={"Authorization": f"Bot {token}"},
            params={"limit": 100},
            timeout=5,
        )
        if resp.status_code != 200:
            return
        for msg in resp.json():
            author = msg.get("author", {})
            if author.get("id") != bot_id:
                continue
            content = msg.get("content", "")
            if display_name in content and match_text in content:
                requests.delete(
                    f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages/{msg['id']}",
                    headers={"Authorization": f"Bot {token}"},
                    timeout=5,
                )
                return
    except Exception:
        pass


def post_core_foods_notification(db: Session, user_id: str, date: str, checked: bool):
    """Post or delete a core foods notification in #pr-city."""
    name = _get_display_name(db, user_id)
    if checked:
        time_ref = _get_time_ref(date)
        content = f"{name} ate their core foods {time_ref}"
        msg_id = _post_message(content)
        if msg_id:
            _react_to_message(msg_id, "\U0001f34e")  # 🍎
    else:
        _find_and_delete_bot_message(name, "ate their core foods")


def post_pr_notification(db: Session, user_id: str, exercise: str, old_1rm: float, new_1rm: float):
    """Post a PR notification in #pr-city when user beats their personal best."""
    if old_1rm <= 0:
        return
    improvement = ((new_1rm - old_1rm) / old_1rm) * 100
    if improvement <= 0:
        return
    name = _get_display_name(db, user_id)
    # Delete any existing PR notification for this exercise first (re-log scenario)
    _find_and_delete_bot_message(name, f"personal best on {exercise}")
    content = f"{name} just beat their last personal best on {exercise} by {improvement:.1f}%"
    msg_id = _post_message(content)
    if msg_id:
        _react_to_message(msg_id, "\U0001f4aa")  # 💪


def post_pr_upgrade_notification(db: Session, user_id: str, exercise: str):
    """Post a PR notification when user upgrades from bodyweight to weighted on an exercise."""
    name = _get_display_name(db, user_id)
    # Delete any existing PR notification for this exercise first (re-log scenario)
    _find_and_delete_bot_message(name, f"personal best on {exercise}")
    content = f"{name} just hit a personal best on {exercise} — upgraded to weighted"
    msg_id = _post_message(content)
    if msg_id:
        _react_to_message(msg_id, "\U0001f4aa")  # 💪


def delete_pr_notification(db: Session, user_id: str, exercise: str):
    """Delete a PR notification from #pr-city when a re-log undoes a PR."""
    name = _get_display_name(db, user_id)
    _find_and_delete_bot_message(name, f"personal best on {exercise}")


def post_workout_completion_notification(db: Session, user_id: str, letter: str, position_started_at=None):
    """Post a clean sweep notification ONLY if every exercise in the workout got a PR during this session window."""
    if not position_started_at:
        return
    
    # Get all exercises for this workout letter
    exercises = db.query(Workout).filter(
        Workout.user_id == user_id,
        Workout.workout_letter == letter,
    ).all()
    
    if not exercises:
        return
    
    ex_names = [e.exercise_name for e in exercises]
    
    # For each exercise, check if there's a PR logged during the session window
    # that improved on the previous best (i.e. is_pr was true at log time)
    # We check: is the best e1RM for this exercise set during or after position_started_at?
    all_pr = True
    for ex_name in ex_names:
        # Get all PRs for this exercise, ordered by timestamp
        prs = db.query(PR).filter(
            PR.user_id == user_id,
            PR.exercise == ex_name,
        ).order_by(PR.timestamp.asc()).all()
        
        # Find PRs logged in this session window
        session_prs = [p for p in prs if p.timestamp >= position_started_at]
        if not session_prs:
            all_pr = False
            break
        
        # Check if the best e1RM in session beats all prior e1RMs
        prior_prs = [p for p in prs if p.timestamp < position_started_at]
        if not prior_prs:
            # First time logging this exercise — not a "beat your best" PR
            all_pr = False
            break
        
        best_prior = max(p.estimated_1rm for p in prior_prs)
        best_session = max(p.estimated_1rm for p in session_prs)
        if best_session <= best_prior:
            all_pr = False
            break
    
    if not all_pr:
        return
    
    name = _get_display_name(db, user_id)
    content = f"{name} just clean swept Workout {letter} with all personal bests"
    msg_id = _post_message(content)
    if msg_id:
        _react_to_message(msg_id, "\U0001f525")  # 🔥


def post_deload_notification(db: Session, user_id: str, strength_pct: float = None):
    """Post a deload notification in #pr-city when a user completes a training cycle."""
    name = _get_display_name(db, user_id)
    if strength_pct is not None and strength_pct > 0:
        content = f"{name} has finished a training cycle and got {strength_pct:.1f}% stronger, time for a well deserved break"
    else:
        content = f"{name} has finished a training cycle and earned a well deserved break"
    msg_id = _post_message(content)
    if msg_id:
        _react_to_message(msg_id, "\U0001f9d8")  # 🧘
