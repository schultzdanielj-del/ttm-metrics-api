#!/usr/bin/env python3
"""
Add Dan's 5-day workout split (A/B/C/D/E)
Run 4x per week on a rotating schedule

Usage:
    python add_workout_plan.py <user_id>
    python add_workout_plan.py 718992882182258769
"""

import requests
import sys

API_BASE_URL = "https://ttm-metrics-api-production.up.railway.app"

def add_workout_plan(user_id):
    """Add Dan's complete 5-day workout split"""
    
    workouts = {
        "A": [
            {"exercise_order": 1, "exercise_name": "Single Arm DB Floor Press", "setup_notes": "", "special_logging": None},
            {"exercise_order": 2, "exercise_name": "Single Arm DB Floor Press", "setup_notes": "", "special_logging": None},
            {"exercise_order": 3, "exercise_name": "Alternating DB Hammer Curl", "setup_notes": "", "special_logging": None},
            {"exercise_order": 4, "exercise_name": "Seated DB Curls", "setup_notes": "", "special_logging": None},
            {"exercise_order": 5, "exercise_name": "Standing DB Curls", "setup_notes": "", "special_logging": None},
            {"exercise_order": 6, "exercise_name": "Reverse Grip EZ Bar Curls", "setup_notes": "", "special_logging": None},
        ],
        "B": [
            {"exercise_order": 1, "exercise_name": "Wide Grip Pullups", "setup_notes": "", "special_logging": None},
            {"exercise_order": 2, "exercise_name": "Chinups", "setup_notes": "", "special_logging": None},
            {"exercise_order": 3, "exercise_name": "Pulldowns", "setup_notes": "", "special_logging": None},
            {"exercise_order": 4, "exercise_name": "Chest Supported DB Rows", "setup_notes": "", "special_logging": None},
            {"exercise_order": 5, "exercise_name": "Single Arm DB Rows", "setup_notes": "", "special_logging": None},
            {"exercise_order": 6, "exercise_name": "Head Supported RDF", "setup_notes": "", "special_logging": None},
        ],
        "C": [
            {"exercise_order": 1, "exercise_name": "DB Front Raises", "setup_notes": "", "special_logging": None},
            {"exercise_order": 2, "exercise_name": "Seated DB Lateral Raises", "setup_notes": "", "special_logging": None},
            {"exercise_order": 3, "exercise_name": "Standing DB Lateral Raises", "setup_notes": "", "special_logging": None},
            {"exercise_order": 4, "exercise_name": "Lying DB Triceps Extensions", "setup_notes": "", "special_logging": None},
            {"exercise_order": 5, "exercise_name": "Incline EZ Bar Triceps Extensions", "setup_notes": "", "special_logging": None},
            {"exercise_order": 6, "exercise_name": "Straight Bar Pushdowns", "setup_notes": "", "special_logging": None},
        ],
        "D": [
            {"exercise_order": 1, "exercise_name": "Front Loaded Barbell Reverse Lunges", "setup_notes": "", "special_logging": None},
            {"exercise_order": 2, "exercise_name": "Heels Elevated Front Squats", "setup_notes": "", "special_logging": None},
            {"exercise_order": 3, "exercise_name": "Glute Ham Raises", "setup_notes": "", "special_logging": None},
            {"exercise_order": 4, "exercise_name": "Barbell Hip Thrusts", "setup_notes": "", "special_logging": None},
            {"exercise_order": 5, "exercise_name": "Reverse Hypers", "setup_notes": "2-4x12-20 reps protocol", "special_logging": None},
        ],
        "E": [
            {"exercise_order": 1, "exercise_name": "Side Planks", "setup_notes": "", "special_logging": "reps_as_seconds"},
            {"exercise_order": 2, "exercise_name": "Roman Chair Situps", "setup_notes": "", "special_logging": None},
            {"exercise_order": 3, "exercise_name": "Rotational Neck Bridges", "setup_notes": "", "special_logging": None},
            {"exercise_order": 4, "exercise_name": "Single Leg Calf Raises", "setup_notes": "", "special_logging": None},
            {"exercise_order": 5, "exercise_name": "Seated Single Leg Calf Raises", "setup_notes": "", "special_logging": None},
            {"exercise_order": 6, "exercise_name": "Standing Dip Belt Calf Raises", "setup_notes": "", "special_logging": None},
        ]
    }
    
    print(f"Adding 5-day workout split for user {user_id}...")
    print()
    
    for letter, exercises in workouts.items():
        print(f"Creating Workout {letter}...")
        response = requests.post(
            f"{API_BASE_URL}/api/workouts",
            json={
                "user_id": user_id,
                "workout_letter": letter,
                "exercises": exercises
            }
        )
        
        if response.status_code == 200:
            print(f"  ✅ Workout {letter} created ({len(exercises)} exercises)")
        else:
            print(f"  ❌ Error creating Workout {letter}: {response.status_code}")
            print(f"  {response.text}")
    
    print()
    print("✅ All 5 workouts created!")
    print()
    print("Workouts:")
    print("  A - Arms (Press/Curls)")
    print("  B - Back/Pull")
    print("  C - Shoulders/Triceps")
    print("  D - Legs")
    print("  E - Core/Calves")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python add_workout_plan.py <user_id>")
        print("Example: python add_workout_plan.py 718992882182258769")
        sys.exit(1)
    
    user_id = sys.argv[1]
    add_workout_plan(user_id)
