#!/usr/bin/env python3
"""
Setup Feras's complete dashboard:
  1. Create dashboard member
  2. Create 4-day workout split (A/B/C/D)
  3. Seed best PRs from historical data

Changes from original program:
  - Pec Fly Machine → Flat DB Flys (permanent swap per Dan)

Usage:
    python setup_feras.py
"""

import requests
import sys

API_BASE_URL = "https://ttm-metrics-api-production.up.railway.app"

FERAS_USER_ID = "919580721922859008"
FERAS_USERNAME = "feras"
FERAS_DISPLAY = "Feras"


def create_member():
    """Create Feras's dashboard member account."""
    print("Step 1: Creating dashboard member...")
    resp = requests.post(
        f"{API_BASE_URL}/api/dashboard/members",
        json={"user_id": FERAS_USER_ID, "username": FERAS_DISPLAY}
    )
    if resp.status_code == 200:
        data = resp.json()
        print(f"  ✅ Member created/exists: {data.get('unique_code', 'N/A')}")
        print(f"  Dashboard URL: {data.get('dashboard_url', 'N/A')}")
        return data
    else:
        print(f"  ❌ Error: {resp.status_code} - {resp.text}")
        return None


def create_workouts():
    """Create Feras's 4-day workout split with normalized exercise names."""
    print("\nStep 2: Creating workout plans...")

    workouts = {
        "A": [
            {"exercise_order": 1, "exercise_name": "incline machine bench press", "setup_notes": None, "special_logging": None},
            {"exercise_order": 2, "exercise_name": "single arm flat dumbbell bench press", "setup_notes": None, "special_logging": None},
            {"exercise_order": 3, "exercise_name": "flat dumbbell fly", "setup_notes": None, "special_logging": None},
            {"exercise_order": 4, "exercise_name": "alternating dumbbell hammer curl", "setup_notes": None, "special_logging": None},
            {"exercise_order": 5, "exercise_name": "seated underhand dumbbell curl", "setup_notes": None, "special_logging": None},
            {"exercise_order": 6, "exercise_name": "decline situp", "setup_notes": None, "special_logging": None},
        ],
        "B": [
            {"exercise_order": 1, "exercise_name": "assisted neutral grip chinup machine", "setup_notes": None, "special_logging": None},
            {"exercise_order": 2, "exercise_name": "plated loaded chest supported row", "setup_notes": None, "special_logging": None},
            {"exercise_order": 3, "exercise_name": "wide grip lat pulldown", "setup_notes": None, "special_logging": None},
            {"exercise_order": 4, "exercise_name": "chest supported dumbbell row", "setup_notes": None, "special_logging": None},
            {"exercise_order": 5, "exercise_name": "reverse machine fly", "setup_notes": None, "special_logging": None},
            {"exercise_order": 6, "exercise_name": "rear delt fly", "setup_notes": None, "special_logging": None},
        ],
        "C": [
            {"exercise_order": 1, "exercise_name": "high incline dumbbell bench press", "setup_notes": None, "special_logging": None},
            {"exercise_order": 2, "exercise_name": "seated lateral raise", "setup_notes": None, "special_logging": None},
            {"exercise_order": 3, "exercise_name": "dumbbell kelso shrug", "setup_notes": None, "special_logging": None},
            {"exercise_order": 4, "exercise_name": "tricep press", "setup_notes": "Substitute exercise", "special_logging": None},
            {"exercise_order": 5, "exercise_name": "straight bar pushdown", "setup_notes": None, "special_logging": None},
            {"exercise_order": 6, "exercise_name": "side plank", "setup_notes": "x30-90s/side", "special_logging": "reps_as_seconds"},
        ],
        "D": [
            {"exercise_order": 1, "exercise_name": "atg split squat", "setup_notes": None, "special_logging": None},
            {"exercise_order": 2, "exercise_name": "seated leg curl", "setup_notes": None, "special_logging": None},
            {"exercise_order": 3, "exercise_name": "heels elevated goblet squat", "setup_notes": None, "special_logging": None},
            {"exercise_order": 4, "exercise_name": "45 degree back raise", "setup_notes": None, "special_logging": None},
            {"exercise_order": 5, "exercise_name": "landmine rotation", "setup_notes": None, "special_logging": None},
        ],
    }

    for letter, exercises in workouts.items():
        resp = requests.post(
            f"{API_BASE_URL}/api/workouts",
            json={
                "user_id": FERAS_USER_ID,
                "workout_letter": letter,
                "exercises": exercises
            }
        )
        if resp.status_code == 200:
            print(f"  ✅ Workout {letter}: {len(exercises)} exercises")
        else:
            print(f"  ❌ Workout {letter} error: {resp.status_code} - {resp.text}")


def seed_best_prs():
    """Seed Feras's best PRs from historical data."""
    print("\nStep 3: Seeding best PRs...")

    # Only exercises where Dan has confirmed best performance data
    # Exercises with no data (Flat DB Flys, Decline Situps, Reverse Pec Deck) are skipped
    prs = [
        # Workout A
        ("incline machine bench press", 70, 8),
        ("single arm flat dumbbell bench press", 60, 8),
        # flat dumbbell fly - NO DATA (new exercise replacing pec fly machine)
        ("alternating dumbbell hammer curl", 30, 12),
        ("seated underhand dumbbell curl", 30, 12),
        # decline situp - NO DATA

        # Workout B
        ("assisted neutral grip chinup machine", 75, 20),
        ("plated loaded chest supported row", 80, 20),
        ("wide grip lat pulldown", 90, 15),
        ("chest supported dumbbell row", 50, 15),
        # reverse machine fly - NO DATA
        ("rear delt fly", 25, 20),

        # Workout C
        ("high incline dumbbell bench press", 30, 20),
        ("seated lateral raise", 20, 20),
        ("dumbbell kelso shrug", 30, 20),
        ("tricep press", 70, 20),
        ("straight bar pushdown", 50, 15),
        ("side plank", 0, 90),  # BW/90s

        # Workout D
        ("atg split squat", 25, 15),
        ("seated leg curl", 90, 20),
        ("heels elevated goblet squat", 30, 20),
        ("45 degree back raise", 45, 20),
        ("landmine rotation", 60, 10),
    ]

    inserted = 0
    errors = 0
    for exercise, weight, reps in prs:
        resp = requests.post(
            f"{API_BASE_URL}/api/prs",
            json={
                "user_id": FERAS_USER_ID,
                "username": FERAS_USERNAME,
                "exercise": exercise,
                "weight": float(weight),
                "reps": reps,
                "message_id": f"seed-feras-{exercise.replace(' ', '_')}",
                "channel_id": "seed"
            }
        )
        if resp.status_code == 200:
            data = resp.json()
            w = "BW" if weight == 0 else str(weight)
            pr_flag = " ⭐ PR" if data.get("is_new_pr") else ""
            print(f"  ✅ {exercise}: {w}/{reps}{pr_flag}")
            inserted += 1
        else:
            print(f"  ❌ {exercise}: {resp.status_code} - {resp.text}")
            errors += 1

    print(f"\n  Inserted: {inserted}, Errors: {errors}")


def main():
    print("=" * 60)
    print("FERAS DASHBOARD SETUP")
    print("=" * 60)
    print(f"User ID: {FERAS_USER_ID}")
    print(f"Program: 4-day split (A/B/C/D)")
    print(f"Note: Pec Fly Machine replaced with Flat DB Flys")
    print()

    member = create_member()
    if not member:
        print("Failed to create member. Aborting.")
        sys.exit(1)

    create_workouts()
    seed_best_prs()

    print()
    print("=" * 60)
    print("SETUP COMPLETE")
    print("=" * 60)
    print()
    print("Feras's dashboard is ready.")
    print(f"Access code: {member.get('unique_code', 'check API')}")
    print()
    print("Program summary:")
    print("  A: Chest/Biceps (6 exercises)")
    print("  B: Back (6 exercises)")
    print("  C: Shoulders/Triceps/Core (6 exercises)")
    print("  D: Legs (5 exercises)")
    print()
    print("Exercises with no PR data (will show as 'new'):")
    print("  - flat dumbbell fly (new exercise)")
    print("  - decline situp")
    print("  - reverse machine fly")


if __name__ == "__main__":
    main()
