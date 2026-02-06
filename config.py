"""
XP Rewards Configuration
Adjust these values to change how much XP is awarded for different actions
"""

# ============================================================================
# XP System Toggle
# ============================================================================

# Set to False to disable all XP awards
# Set to True to enable XP system
XP_ENABLED = False

# ============================================================================
# API Auto-Awards (Happen automatically when action occurs)
# ============================================================================

XP_REWARDS_API = {
    # New PR logged (better than previous best)
    "pr": 50,
    
    # Workout completed via dashboard
    "workout_complete": 30,
}

# ============================================================================
# Discord Bot Awards (Bot calls /api/xp/award with these amounts)
# ============================================================================

XP_REWARDS_DISCORD = {
    # Weekly training log submitted
    "weekly_log": 100,
    
    # Core foods check-in
    "core_foods": 25,
    
    # Consistency streaks
    "3_day_streak": 50,
    "7_day_streak": 150,
    "30_day_streak": 500,
    
    # Community participation (future)
    "helping_member": 75,
    "posted_progress_pic": 100,
    
    # Special achievements (future)
    "triple_crown": 200,  # 3 PRs in one workout
    "first_pr": 100,      # First PR ever
}

# ============================================================================
# Level Progression
# ============================================================================

# Level 1 → 2 requires this much XP
LEVEL_1_XP = 500

# Each subsequent level requires: 250 + (level * 250)
# Level 2 → 3: 750 XP
# Level 3 → 4: 1000 XP
# Level 4 → 5: 1250 XP
# etc.

LEVEL_BASE = 250
LEVEL_MULTIPLIER = 250

# ============================================================================
# Usage Notes
# ============================================================================

"""
TO ENABLE XP SYSTEM:
    Change XP_ENABLED = True in this file
    Restart the API
    XP will start being awarded automatically

TO DISABLE XP SYSTEM:
    Change XP_ENABLED = False
    XP awards will be skipped (but data is still tracked)
    
XP data is always stored in database, just not awarded when disabled.
You can enable it later and all existing PRs/workouts remain in the database.

To use in main.py:
    from config import XP_REWARDS_API
    award_xp_internal(db, user_id, username, XP_REWARDS_API["pr"], "pr")

To use in Discord bot:
    from config import XP_REWARDS_DISCORD
    requests.post(f"{API_URL}/api/xp/award", json={
        "user_id": user_id,
        "username": username,
        "xp_amount": XP_REWARDS_DISCORD["weekly_log"],
        "reason": "weekly_log"
    })
"""
