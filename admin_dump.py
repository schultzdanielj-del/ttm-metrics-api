"""
Admin endpoint for dumping all Discord PR channel messages with parse analysis.
Import and register with the FastAPI app in main.py.
"""

import os
import time
import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter()

ADMIN_KEY = os.getenv("ADMIN_KEY", "4ifQC_DLzlXM1c5PC6egwvf2p5GgbMR3")


def calculate_1rm(weight: float, reps: int) -> float:
    if weight == 0:
        return reps
    return (weight * reps * 0.0333) + weight


@router.get("/api/admin/dump-messages", tags=["Admin"])
def admin_dump_messages(key: str = ""):
    """
    Fetch all messages from Discord PR channel and return as plain text dump.
    Shows raw content, what the parser extracted, and what was skipped.
    Usage: GET /api/admin/dump-messages?key=<ADMIN_KEY>
    """
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    from scrape_and_reload import (
        parse_message, USER_MAP, PR_CHANNEL_ID
    )

    DISCORD_BOT_TOKEN = os.getenv("TTM_BOT_TOKEN", "")
    if not DISCORD_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TTM_BOT_TOKEN not set in environment")

    # Fetch all messages
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    all_messages = []
    before = None

    while True:
        params = {"limit": 100}
        if before:
            params["before"] = before
        resp = requests.get(
            f"https://discord.com/api/v10/channels/{PR_CHANNEL_ID}/messages",
            headers=headers, params=params
        )
        if resp.status_code == 429:
            retry_after = resp.json().get("retry_after", 1)
            time.sleep(retry_after + 0.5)
            continue
        if resp.status_code != 200:
            return PlainTextResponse(f"Discord API error: {resp.status_code}")
        messages = resp.json()
        if not messages:
            break
        all_messages.extend(messages)
        before = messages[-1]["id"]
        if len(messages) < 100:
            break
        time.sleep(0.5)

    all_messages.reverse()

    lines = []
    lines.append(f"=== PR CHANNEL MESSAGE DUMP ===")
    lines.append(f"Total messages: {len(all_messages)}")
    lines.append(f"Channel ID: {PR_CHANNEL_ID}")
    lines.append(f"")

    total_parsed = 0
    total_skipped = 0

    for msg in all_messages:
        author = msg.get("author", {})
        author_id = author.get("id", "")
        author_name = author.get("username", "unknown")
        content = msg.get("content", "")
        message_id = msg.get("id", "")
        timestamp = msg.get("timestamp", "")
        is_bot = author.get("bot", False)

        lines.append(f"--- MSG {message_id} ---")
        lines.append(f"  Time: {timestamp}")
        lines.append(f"  Author: {author_name} ({author_id})")
        lines.append(f"  Bot: {is_bot}")
        lines.append(f"  In USER_MAP: {author_id in USER_MAP}")

        # Show raw content with visible line breaks
        for i, line in enumerate(content.split('\n')):
            lines.append(f"  Content[{i}]: {repr(line)}")

        # Parse attempt
        if is_bot:
            lines.append(f"  >> SKIPPED: bot message")
            total_skipped += 1
        elif author_id not in USER_MAP:
            lines.append(f"  >> SKIPPED: author not in USER_MAP")
            total_skipped += 1
        else:
            prs = parse_message(content)
            if prs:
                for exercise, weight, reps in prs:
                    e1rm = calculate_1rm(weight, reps)
                    lines.append(f"  >> PARSED: {exercise} | {weight}/{reps} | e1rm={round(e1rm, 1)}")
                    total_parsed += 1
            else:
                lines.append(f"  >> NO PARSE: parser returned empty for this message")
                total_skipped += 1

        lines.append(f"")

    lines.append(f"=== SUMMARY ===")
    lines.append(f"Total messages: {len(all_messages)}")
    lines.append(f"Total PRs parsed: {total_parsed}")
    lines.append(f"Total skipped/no-parse: {total_skipped}")

    return PlainTextResponse("\n".join(lines))
