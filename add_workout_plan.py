#!/usr/bin/env python3
"""
Script to add workout plans to the database
Run this to set up a user's program
"""

from database import SessionLocal, Workout
import sys

def add_workout_plan(user_id: str, workout_letter: str, exercises: list):
    """
    Add exercises to a workout
    exercises: list of tuples (exercise_name, special_logging, setup_notes, video_link)
    
    Example:
    add_workout_plan("123456", "A", [
        ("Squat", None, "Bar on traps", None),
        ("Bench Press", None, "Arch back", None),
        ("Barbell Row", None, "Pull to sternum", None)
    ])
    """
    db = SessionLocal()
    
    try:
        # Delete existing exercises for this workout
        db.query(Workout).filter(
            Workout.user_id == user_id,
            Workout.workout_letter == workout_letter
        ).delete()
        
        # Add new exercises
        for order, (exercise_name, special_logging, setup_notes, video_link) in enumerate(exercises, 1):
            workout = Workout(
                user_id=user_id,
                workout_letter=workout_letter,
                exercise_order=order,
                exercise_name=exercise_name,
                special_logging=special_logging,
                setup_notes=setup_notes,
                video_link=video_link
            )
            db.add(workout)
        
        db.commit()
        print(f"✅ Added {len(exercises)} exercises to Workout {workout_letter} for user {user_id}")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
    finally:
        db.close()

def create_full_program(user_id: str):
    """
    Example: Create a full 2-day program
    Customize this for each user
    """
    # Workout A
    add_workout_plan(user_id, "A", [
        ("Squat", None, None, None),
        ("Bench Press", None, None, None),
        ("Barbell Row", None, None, None),
    ])
    
    # Workout B
    add_workout_plan(user_id, "B", [
        ("Deadlift", None, None, None),
        ("Overhead Press", None, None, None),
        ("Pull Ups", None, None, None),
    ])

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python add_workout_plan.py <user_id>")
        print("\nThis will create a default 2-day program (A/B split)")
        print("Edit the script to customize exercises")
        sys.exit(1)
    
    user_id = sys.argv[1]
    create_full_program(user_id)
    print(f"\n✅ Full program created for user {user_id}")
