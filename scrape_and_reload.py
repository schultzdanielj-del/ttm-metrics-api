"""
TTM Discord PR Channel Scraper & Database Reloader
===================================================
One-shot script to:
1. Scrape all messages from the PR channel since inception
2. Parse PR data from each message
3. Normalize exercise names with the fixed normalization function
4. POST cleaned records to the TTM Metrics API
5. Deduplicate against existing records (by message_id)

Usage:
  python scrape_and_reload.py              # Dry run (prints what it would do)
  python scrape_and_reload.py --execute    # Actually insert into database
  python scrape_and_reload.py --wipe       # Wipe all existing PRs first, then insert

Environment variables needed:
  TTM_BOT_TOKEN  - Discord bot token (already in Railway env)
  API_BASE_URL   - API base URL (defaults to https://ttm-metrics-api-production.up.railway.app)
"""

import os
import re
import sys
import json
import time
import requests
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple

# =============================================================================
# Configuration
# =============================================================================

DISCORD_BOT_TOKEN = os.getenv("TTM_BOT_TOKEN", "")
API_BASE_URL = os.getenv("API_BASE_URL", "https://ttm-metrics-api-production.up.railway.app")
PR_CHANNEL_ID = "1459000944028028970"

# Discord user ID -> (username for API, display name)
USER_MAP = {
    "718992882182258769": ("dans4729", "Dan Schultz"),
    "919580721922859008": ("feras", "Feras"),
    "607043556162666514": ("john", "John"),
    "188471109363040256": ("travis", "Travis"),
    "103351819119398912": ("dan_i", "Dan I"),
    "780219213389234196": ("dan_s", "Dan S"),
}

BOT_IDS = set()

# =============================================================================
# Exercise Name Normalization (finalized version)
# =============================================================================

def normalize_exercise_name(exercise: str, weight: Optional[float] = None) -> str:
    if exercise.strip().startswith('*'):
        return ""

    # 1. PREPROCESSING
    exercise = exercise.lower().strip()
    exercise = re.sub(r'\s+', ' ', exercise)
    exercise = exercise.replace('.', '').replace(',', '')
    exercise = re.sub(r'\([^)]*\)', '', exercise)
    exercise = exercise.replace('-', ' ')
    exercise = re.sub(r'\s+', ' ', exercise).strip()

    # 2. TYPO CORRECTIONS
    typo_map = [
        (r'\bweighte\b', 'weighted'),
        (r'\bex bar\b', 'ez bar'),
        (r'\bdumbell\b', 'dumbbell'),
        (r'\bbarbel\b', 'barbell'),
        (r'\bmilitery\b', 'military'),
        (r'\bmillitary\b', 'military'),
        (r'\bromainian\b', 'romanian'),
        (r'\bromaninan\b', 'romanian'),
        (r'\bstragiht\b', 'straight'),
        (r'\bskullcrushers?\b', 'tricep extension'),
    ]
    for pattern, correction in typo_map:
        exercise = re.sub(pattern, correction, exercise)

    # 3. STRIP "THE"
    if exercise.startswith('the '):
        exercise = exercise[4:]

    # 4. ABBREVIATION EXPANSION
    exercise = re.sub(r'\bdb\b', 'dumbbell', exercise)
    exercise = re.sub(r'\bbb\b', 'barbell', exercise)
    exercise = re.sub(r'\bbw\b', 'bodyweight', exercise)
    exercise = re.sub(r'\bkb\b', 'kettlebell', exercise)
    exercise = re.sub(r'\bsl\b', 'single leg', exercise)
    exercise = re.sub(r'\bsa\b', 'single arm', exercise)
    exercise = re.sub(r'\bcs\b', 'chest supported', exercise)
    exercise = re.sub(r'\bhs\b', 'head supported', exercise)
    exercise = re.sub(r'\bdm\b', 'dumbbell', exercise)
    exercise = re.sub(r'\b1 arm\b', 'single arm', exercise)
    if 'ez' in exercise and 'ez bar' not in exercise:
        exercise = re.sub(r'\bez\b', 'ez bar', exercise)

    if re.search(r'\boh\b.*\b(pulldown|pullup|row|curl)', exercise) or \
       re.search(r'\b(pulldown|pullup|row|curl).*\boh\b', exercise):
        exercise = re.sub(r'\boh\b', 'overhand', exercise)
    else:
        exercise = re.sub(r'\boh\b', 'overhead', exercise)

    exercise = re.sub(r'\buh\b', 'underhand', exercise)

    # 5. EQUIPMENT SYNONYM NORMALIZATION
    exercise = re.sub(r'\bsuspension trainer\b', 'trx', exercise)
    exercise = re.sub(r'\bsuspension\b', 'trx', exercise)
    exercise = re.sub(r'\bcables\b', 'cable', exercise)
    exercise = re.sub(r'\bez curl bar\b', 'ez bar', exercise)
    exercise = re.sub(r'\beasy bar\b', 'ez bar', exercise)
    exercise = re.sub(r'\bsmith\b(?! machine)', 'smith machine', exercise)
    exercise = re.sub(r'\btoe press\b', 'leg press calf raise', exercise)

    exercise = re.sub(r'\bswiss ball leg curl\b', 'stability ball leg curl', exercise)
    exercise = re.sub(r'\bball leg curl\b', 'stability ball leg curl', exercise)
    exercise = re.sub(r'\bgliding disk leg curl\b', 'slider leg curl', exercise)
    exercise = re.sub(r'\bgliding leg curl\b', 'slider leg curl', exercise)
    exercise = re.sub(r'\btowel leg curl\b', 'slider leg curl', exercise)

    exercise = re.sub(r'\bband assisted\b', 'band assisted', exercise)
    if 'chinup' in exercise or 'pullup' in exercise:
        exercise = re.sub(r'\bbanded\b', 'band assisted', exercise)

    # 6. COMPOUND WORD NORMALIZATION
    compound_words = [
        ('chin up', 'chinup'), ('chin ups', 'chinups'),
        ('pull up', 'pullup'), ('pull ups', 'pullups'),
        ('push up', 'pushup'), ('push ups', 'pushups'),
        ('sit up', 'situp'), ('sit ups', 'situps'),
        ('step up', 'stepup'), ('step ups', 'stepups'),
        ('face pull', 'facepull'), ('face pulls', 'facepulls'),
        ('push down', 'pushdown'), ('push downs', 'pushdowns'),
        ('pull down', 'pulldown'), ('pull downs', 'pulldowns'),
    ]
    for spaced, compound in compound_words:
        exercise = exercise.replace(spaced, compound)

    # 7. PLURAL TO SINGULAR NORMALIZATION
    plural_map = [
        (r'\braises\b', 'raise'),
        (r'\bextensions\b', 'extension'),
        (r'\bcurls\b', 'curl'),
        (r'\brows\b', 'row'),
        (r'\bpresses\b', 'press'),
        (r'\bflies\b', 'fly'),
        (r'\bshrugs\b', 'shrug'),
        (r'\bsquats\b', 'squat'),
        (r'\blunges\b', 'lunge'),
        (r'\bplanks\b', 'plank'),
        (r'\brotations\b', 'rotation'),
        (r'\bmines\b', 'mine'),
        (r'\bpullups\b', 'pullup'),
        (r'\bchinups\b', 'chinup'),
        (r'\bpushups\b', 'pushup'),
        (r'\bdips\b', 'dip'),
        (r'\bpushdowns\b', 'pushdown'),
        (r'\bpulldowns\b', 'pulldown'),
        (r'\bfacepulls\b', 'facepull'),
        (r'\bstepups\b', 'stepup'),
        (r'\bsitups\b', 'situp'),
        (r'\bdeadlifts\b', 'deadlift'),
        (r'\bthrusts\b', 'thrust'),
        (r'\brollouts\b', 'rollout'),
        (r'\bbridges\b', 'bridge'),
        (r'\bangels\b', 'angel'),
        (r'\blandmines\b', 'landmine'),
        (r'\bhypers\b', 'hyper'),
        (r'\bdeadbugs\b', 'deadbug'),
    ]
    for pattern, replacement in plural_map:
        exercise = re.sub(pattern, replacement, exercise)

    # 8. POSITION & MODIFIER STANDARDIZATION
    exercise = re.sub(r'\bpause rep\b', 'paused', exercise)
    exercise = re.sub(r'\bunderhand grip\b', 'underhand', exercise)
    exercise = re.sub(r'\boverhand grip\b', 'overhand', exercise)
    exercise = re.sub(r'\bbody weight\b', 'bodyweight', exercise)
    exercise = re.sub(r'\bland mine\b', 'landmine', exercise)
    exercise = re.sub(r'\bglut\b', 'glute', exercise)
    if exercise.endswith(' bench') and 'press' not in exercise:
        exercise = exercise + ' press'
    # Word order: "dumbbell seated X" -> "seated dumbbell X"
    exercise = re.sub(r'\bdumbbell (seated|standing|incline|flat|decline)\b', r'\1 dumbbell', exercise)
    # "trx bicep tricep extension" -> "trx tricep extension"
    exercise = re.sub(r'\btrx bicep tricep\b', 'trx tricep', exercise)
    # Strip trailing descriptors
    exercise = re.sub(r'\s+\d+\s*second.*$', '', exercise)
    exercise = re.sub(r'\s+(each|per)\s+side$', '', exercise)
    exercise = re.sub(r'\s+x\d+$', '', exercise)

    # 9. EXERCISE-SPECIFIC RULES

    if 'lateral' in exercise and 'raise' not in exercise:
        exercise = re.sub(r'\blateral(s)?\b', 'lateral raise', exercise)
    exercise = re.sub(r'\blat raise(s)?\b', 'lateral raise', exercise)

    if 'extension' in exercise and 'tricep' not in exercise:
        if not re.search(r'\b(leg|back|hip|hyper|reverse)\b', exercise):
            exercise = re.sub(r'\bextension(s)?\b', 'tricep extension', exercise)

    exercise = re.sub(r'\btriceps\b', 'tricep', exercise)

    exercise = re.sub(r'\bhyperextension\b', 'back extension', exercise)
    exercise = re.sub(r'\bhyper\b(?! extension)', 'back extension', exercise)

    exercise = re.sub(r'\breverse hyper extension\b', 'reverse hyper', exercise)
    exercise = re.sub(r'\breverse hyperextension\b', 'reverse hyper', exercise)

    if exercise == 'curl' or exercise == 'curls':
        exercise = 'bicep curl'
    exercise = re.sub(r'\bbiceps curl\b', 'bicep curl', exercise)
    exercise = re.sub(r'\bcable curl\b', 'cable bicep curl', exercise)

    exercise = re.sub(r'\bflat bench press\b', 'bench press', exercise)
    exercise = re.sub(r'\bincline press\b', 'incline bench press', exercise)
    exercise = re.sub(r'\bdecline press\b', 'decline bench press', exercise)
    if 'dumbbell' in exercise and 'press' in exercise and 'bench' not in exercise and 'military' not in exercise:
        exercise = exercise.replace('dumbbell press', 'dumbbell bench press')

    exercise = re.sub(r'\bshoulder press\b', 'military press', exercise)
    exercise = re.sub(r'\boverhead press\b', 'military press', exercise)

    exercise = re.sub(r'\bbent over barbell row\b', 'barbell row', exercise)
    exercise = re.sub(r'\bbent row\b', 'barbell row', exercise)

    if re.match(r'^dumbbell row$', exercise):
        exercise = 'single arm dumbbell row'
    exercise = re.sub(r'\bone arm dumbbell row\b', 'single arm dumbbell row', exercise)

    exercise = re.sub(r'\bbent dumbbell row\b', 'bent over dumbbell row', exercise)

    if re.match(r'^pulldown$', exercise):
        exercise = 'lat pulldown'
    exercise = re.sub(r'\bwide grip pulldown\b', 'wide grip lat pulldown', exercise)
    exercise = re.sub(r'\bwide pulldown\b', 'wide grip lat pulldown', exercise)
    exercise = re.sub(r'\bclose grip pulldown\b', 'close grip lat pulldown', exercise)
    exercise = re.sub(r'\bclose pulldown\b', 'close grip lat pulldown', exercise)

    exercise = re.sub(r'\bpulls\b', 'pullup', exercise)
    exercise = re.sub(r'\bchins\b', 'chinup', exercise)

    if weight is not None and 'squat' in exercise:
        if re.match(r'^squat$', exercise):
            if weight == 0:
                exercise = 'bodyweight squat'
            elif weight > 15:
                exercise = 'barbell back squat'

    exercise = re.sub(r'\bdumbbell goblet squat\b', 'goblet squat', exercise)
    exercise = re.sub(r'\bkettlebell goblet squat\b', 'goblet squat', exercise)

    exercise = re.sub(r'\bbulgarian split squat\b', 'rear foot elevated split squat', exercise)

    if re.match(r'^deadlift$', exercise):
        exercise = 'conventional deadlift'
    exercise = re.sub(r'\bsumo\b(?! deadlift)', 'sumo deadlift', exercise)
    exercise = re.sub(r'\bhex bar deadlift\b', 'trap bar deadlift', exercise)

    exercise = re.sub(r'\bbarbell hip thrust\b', 'hip thrust', exercise)

    exercise = re.sub(r'\bparallel bar dip\b', 'dip', exercise)

    exercise = re.sub(r'\bcable facepull\b', 'facepull', exercise)
    exercise = re.sub(r'\brope facepull\b', 'facepull', exercise)

    exercise = re.sub(r'\bflye(s)?\b', 'fly', exercise)
    exercise = re.sub(r'\bflys\b', 'fly', exercise)
    exercise = re.sub(r'\bpec deck\b', 'machine fly', exercise)
    exercise = re.sub(r'\breverse fly\b', 'rear delt fly', exercise)
    exercise = re.sub(r'\bbent over fly\b', 'rear delt fly', exercise)
    exercise = re.sub(r'\brear fly\b', 'rear delt fly', exercise)

    exercise = re.sub(r'\btrap shrug\b', 'shrug', exercise)

    exercise = re.sub(r'\bcalf raises\b', 'calf raise', exercise)
    if re.match(r'^calf raise$', exercise):
        exercise = 'standing calf raise'

    exercise = re.sub(r'\bab wheel rollout\b', 'ab rollout', exercise)
    exercise = re.sub(r'\bab wheel rotation\b', 'ab rollout', exercise)
    if re.match(r'^ab wheel$', exercise):
        exercise = 'ab rollout'
    if re.match(r'^rollout$', exercise):
        exercise = 'ab rollout'

    exercise = re.sub(r'\bhang from bar\b', 'dead hang', exercise)
    exercise = re.sub(r'\bbar hang\b', 'dead hang', exercise)

    if re.match(r'^pushdown(s)?$', exercise):
        exercise = 'tricep pushdown'
    exercise = re.sub(r'\bv bar pushdown\b', 'tricep pushdown', exercise)
    exercise = re.sub(r'\bv.bar pushdown\b', 'tricep pushdown', exercise)
    exercise = re.sub(r'\bez bar pushdown\b', 'tricep pushdown', exercise)

    exercise = re.sub(r'\bpushdowns\b', 'pushdown', exercise)

    exercise = re.sub(r'\bbarbell good morning\b', 'good morning', exercise)

    if re.match(r'^pullover$', exercise):
        exercise = 'dumbbell pullover'
    exercise = re.sub(r'\bstraight arm pulldown\b', 'cable pullover', exercise)

    exercise = re.sub(r'\bchest press machine\b', 'machine chest press', exercise)

    exercise = re.sub(r'\bext rotation\b', 'external rotation', exercise)

    exercise = re.sub(r'\b\d+ \d+ \d+\b', '', exercise)

    # 10. INCLINE ANGLE NORMALIZATION
    if 'press' in exercise:
        exercise = re.sub(r'\b(30 degree|low) incline\b', 'low incline', exercise)
        exercise = re.sub(r'\b(60 degree|high|steep) incline\b', 'high incline', exercise)
        exercise = re.sub(r'\b45 degree incline\b', 'incline', exercise)

    # 11. REMOVE DUPLICATE CONSECUTIVE WORDS
    words = exercise.split()
    if words:
        deduplicated = [words[0]]
        for i in range(1, len(words)):
            if words[i] != words[i-1]:
                deduplicated.append(words[i])
        exercise = ' '.join(deduplicated)

    exercise = re.sub(r'\s+', ' ', exercise).strip()
    return exercise


# =============================================================================
# Message Parsing
# =============================================================================

def parse_weight_reps(text: str) -> List[Tuple[str, float, int]]:
    results = []

    line = text.strip()
    if not line:
        return results

    # Skip non-PR content
    skip_patterns = [
        r'^core\s*foods?\s*(eaten|checked|done)',
        r'^ate\s*(my|the)?\s*core\s*foods?',
        r'^\*',
        r'^(sorry|oops|my bad|wait|actually)',
        r'^(what|how|why|when|where|who|is|are|do|does|can|could|should|would)',
        r'^(yessir|yes|no|yeah|nah|lol|haha|nice|great|awesome|thanks)',
        r'^(needed|grinding|another|holy|you)',
        r'^(i |i\'m|i\'ve|i\'ll|the |it |err )',
        r'^(s&p |what\'s|from the)',
        r'^(off to|just go|say |make it|wtf )',
        r'^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d',
        r'^\d+\s*set\s',
        r'^"',
        r'^@',
        r'^(shoulders?\s*&|back\s*&|legs?\s*&|chest\s*&|arms?\s*&)',
    ]
    for pattern in skip_patterns:
        if re.match(pattern, line, re.IGNORECASE):
            return results

    # Skip lines too long to be a PR
    if len(line) > 120:
        return results

    # Pattern 1: "Exercise Name - Weight lbs x Reps (optional notes)"
    match_dash = re.match(
        r'^(.+?)\s*[-\u2013]\s*(\d+\.?\d*)\s*(?:lbs?)?\s*x\s*(\d+)',
        line, re.IGNORECASE
    )
    if match_dash:
        name = match_dash.group(1).strip()
        weight = float(match_dash.group(2))
        reps = int(match_dash.group(3))
        normalized = normalize_exercise_name(name, weight)
        if normalized:
            results.append((normalized, weight, reps))
        return results

    # Pattern 2: "Exercise Name Weight/Reps" or "Exercise Name BW/Reps"
    match_slash = re.match(
        r'^(.+?)\s+(bw|\d+\.?\d*)\s*/\s*(\d+)',
        line, re.IGNORECASE
    )
    if match_slash:
        name = match_slash.group(1).strip()
        weight_str = match_slash.group(2)
        reps = int(match_slash.group(3))
        weight = 0.0 if weight_str.lower() == 'bw' else float(weight_str)
        normalized = normalize_exercise_name(name, weight)
        if normalized:
            results.append((normalized, weight, reps))
        return results

    # Pattern 3: "Exercise Name WeightxReps"
    match_x = re.match(
        r'^(.+?)\s+(\d+\.?\d*)\s*x\s*(\d+)',
        line, re.IGNORECASE
    )
    if match_x:
        name = match_x.group(1).strip()
        weight = float(match_x.group(2))
        reps = int(match_x.group(3))
        normalized = normalize_exercise_name(name, weight)
        if normalized:
            results.append((normalized, weight, reps))
        return results

    return results


def parse_message(content: str) -> List[Tuple[str, float, int]]:
    all_prs = []
    lines = content.split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue
        prs = parse_weight_reps(line)
        all_prs.extend(prs)

    return all_prs


# =============================================================================
# Discord API Functions
# =============================================================================

def discord_get(endpoint: str, params: dict = None) -> dict:
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    url = f"https://discord.com/api/v10{endpoint}"
    resp = requests.get(url, headers=headers, params=params)

    if resp.status_code == 429:
        retry_after = resp.json().get("retry_after", 1)
        print(f"  Rate limited, waiting {retry_after}s...")
        time.sleep(retry_after + 0.5)
        return discord_get(endpoint, params)

    resp.raise_for_status()
    return resp.json()


def fetch_all_messages(channel_id: str) -> List[dict]:
    all_messages = []
    before = None
    batch_num = 0

    while True:
        batch_num += 1
        params = {"limit": 100}
        if before:
            params["before"] = before

        messages = discord_get(f"/channels/{channel_id}/messages", params)

        if not messages:
            break

        all_messages.extend(messages)
        before = messages[-1]["id"]

        print(f"  Batch {batch_num}: fetched {len(messages)} messages (total: {len(all_messages)})")

        if len(messages) < 100:
            break

        time.sleep(0.5)

    all_messages.reverse()
    return all_messages


# =============================================================================
# API Functions
# =============================================================================

def get_existing_message_ids() -> set:
    resp = requests.get(f"{API_BASE_URL}/api/prs?limit=10000")
    if resp.status_code == 200:
        prs = resp.json()
        return {pr.get("message_id", "") for pr in prs if pr.get("message_id")}
    return set()


def get_current_pr_count() -> int:
    resp = requests.get(f"{API_BASE_URL}/api/prs/count")
    if resp.status_code == 200:
        data = resp.json()
        return data.get("total_prs", 0)
    return 0


def post_pr(user_id: str, username: str, exercise: str, weight: float,
            reps: int, message_id: str, channel_id: str) -> dict:
    payload = {
        "user_id": user_id,
        "username": username,
        "exercise": exercise,
        "weight": weight,
        "reps": reps,
        "message_id": message_id,
        "channel_id": channel_id
    }
    resp = requests.post(f"{API_BASE_URL}/api/prs", json=payload)
    if resp.status_code == 200:
        return resp.json()
    else:
        print(f"  ERROR posting PR: {resp.status_code} - {resp.text}")
        return {}


def wipe_all_prs():
    resp = requests.get(f"{API_BASE_URL}/api/prs?limit=10000")
    if resp.status_code != 200:
        print(f"ERROR: Could not fetch PRs: {resp.status_code}")
        return 0

    prs = resp.json()

    message_ids = set()
    for pr in prs:
        mid = pr.get("message_id", "")
        if mid:
            message_ids.add(mid)

    deleted = 0
    for mid in message_ids:
        resp = requests.delete(f"{API_BASE_URL}/api/prs/message/{mid}")
        if resp.status_code == 200:
            data = resp.json()
            deleted += data.get("deleted_count", 0)

    print(f"Wiped {deleted} PRs from database ({len(message_ids)} unique message_ids)")
    return deleted


# =============================================================================
# Main Script
# =============================================================================

def main():
    mode = "dry_run"
    if "--execute" in sys.argv:
        mode = "execute"
    elif "--wipe" in sys.argv:
        mode = "wipe_and_execute"

    print("=" * 60)
    print("TTM Discord PR Channel Scraper & Database Reloader")
    print("=" * 60)
    print(f"Mode: {mode}")
    print(f"API: {API_BASE_URL}")
    print(f"Channel: {PR_CHANNEL_ID}")
    print(f"Bot token: {'SET' if DISCORD_BOT_TOKEN else 'MISSING'}")
    print()

    if not DISCORD_BOT_TOKEN:
        print("ERROR: TTM_BOT_TOKEN environment variable not set!")
        print("Set it with: export TTM_BOT_TOKEN=your_token_here")
        sys.exit(1)

    # Step 1: Fetch all messages
    print("Step 1: Fetching all messages from PR channel...")
    messages = fetch_all_messages(PR_CHANNEL_ID)
    print(f"  Total messages fetched: {len(messages)}")
    print()

    # Step 2: Parse messages into PR records
    print("Step 2: Parsing messages for PR data...")
    parsed_prs = []
    skipped_authors = set()

    for msg in messages:
        author = msg.get("author", {})
        author_id = author.get("id", "")
        author_name = author.get("username", "unknown")
        content = msg.get("content", "")
        message_id = msg.get("id", "")
        timestamp = msg.get("timestamp", "")

        if author.get("bot", False):
            continue

        if author_id not in USER_MAP:
            skipped_authors.add(f"{author_name} ({author_id})")
            continue

        username, display_name = USER_MAP[author_id]

        prs = parse_message(content)

        for exercise, weight, reps in prs:
            parsed_prs.append({
                "user_id": author_id,
                "username": username,
                "display_name": display_name,
                "exercise": exercise,
                "weight": weight,
                "reps": reps,
                "message_id": message_id,
                "channel_id": PR_CHANNEL_ID,
                "timestamp": timestamp,
                "raw_content": content[:100]
            })

    print(f"  Total PRs parsed: {len(parsed_prs)}")
    if skipped_authors:
        print(f"  Skipped unknown authors: {skipped_authors}")
    print()

    # Step 3: Summary by user
    print("Step 3: Summary by user:")
    user_counts = {}
    for pr in parsed_prs:
        name = pr["display_name"]
        user_counts[name] = user_counts.get(name, 0) + 1
    for name, count in sorted(user_counts.items()):
        print(f"  {name}: {count} PRs")
    print()

    # Step 4: Show unique exercises
    print("Step 4: Unique normalized exercise names:")
    exercises = set()
    for pr in parsed_prs:
        exercises.add(pr["exercise"])
    for ex in sorted(exercises):
        print(f"  - {ex}")
    print(f"  Total unique exercises: {len(exercises)}")
    print()

    # Step 5: Show sample PRs
    print("Step 5: Sample parsed PRs (first 20):")
    for pr in parsed_prs[:20]:
        w = "BW" if pr["weight"] == 0 else f"{pr['weight']}"
        print(f"  [{pr['display_name']}] {pr['exercise']} {w}/{pr['reps']}  (msg: {pr['message_id'][:8]}...)")
    print()

    if mode == "dry_run":
        print("=" * 60)
        print("DRY RUN COMPLETE - No changes made to database.")
        print(f"Would insert {len(parsed_prs)} PRs.")
        print("Run with --execute to insert, or --wipe to wipe and insert.")
        print("=" * 60)
        return

    # Step 6: Optionally wipe existing data
    if mode == "wipe_and_execute":
        print("Step 6: Wiping existing PRs from database...")
        wipe_all_prs()
        print()

    # Step 7: Get existing message IDs for dedup
    print("Step 7: Checking for existing records (deduplication)...")
    existing_ids = get_existing_message_ids()
    print(f"  Existing message_ids in database: {len(existing_ids)}")

    # Step 8: Insert new PRs
    print("Step 8: Inserting PRs...")
    inserted = 0
    skipped_dedup = 0
    errors = 0

    for i, pr in enumerate(parsed_prs):
        if pr["message_id"] in existing_ids and mode != "wipe_and_execute":
            skipped_dedup += 1
            continue

        result = post_pr(
            user_id=pr["user_id"],
            username=pr["username"],
            exercise=pr["exercise"],
            weight=pr["weight"],
            reps=pr["reps"],
            message_id=pr["message_id"],
            channel_id=pr["channel_id"]
        )

        if result:
            inserted += 1
        else:
            errors += 1

        if (i + 1) % 50 == 0:
            print(f"  Progress: {i + 1}/{len(parsed_prs)} (inserted: {inserted}, skipped: {skipped_dedup}, errors: {errors})")

        time.sleep(0.05)

    print()
    print("=" * 60)
    print("COMPLETE!")
    print(f"  Total parsed: {len(parsed_prs)}")
    print(f"  Inserted: {inserted}")
    print(f"  Skipped (dedup): {skipped_dedup}")
    print(f"  Errors: {errors}")
    print("=" * 60)

    # Step 9: Verify
    print()
    print("Step 9: Verification...")
    final_count = get_current_pr_count()
    print(f"  Final PR count in database: {final_count}")


if __name__ == "__main__":
    main()
