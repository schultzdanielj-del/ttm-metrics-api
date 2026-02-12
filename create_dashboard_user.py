#!/usr/bin/env python3
"""
Script to create dashboard members and generate unique access codes
Run this to give users access to the dashboard
"""

import requests
import sys

API_URL = "https://ttm-metrics-api-production.up.railway.app"

def create_dashboard_member(user_id: str, username: str):
    """
    Create a dashboard member and get their unique access code
    """
    response = requests.post(
        f"{API_URL}/api/dashboard/members",
        json={
            "user_id": user_id,
            "username": username
        }
    )
    
    if response.status_code == 200:
        data = response.json()
        print(f"\n✅ Dashboard access created for {username}")
        print(f"User ID: {data['user_id']}")
        print(f"Access Code: {data['unique_code']}")
        print(f"\nShare this link with {username}:")
        print(f"https://dashboard-production-79f2.up.railway.app")
        print(f"\nThey should enter this code: {data['unique_code']}")
        return data
    else:
        print(f"❌ Error: {response.status_code}")
        print(response.text)
        return None

def create_workout_plan(user_id: str, workouts: dict):
    """
    Create workout plan for a user
    workouts: {
        'A': [('Squat', None), ('Bench Press', None)],
        'B': [('Deadlift', None), ('Overhead Press', None)]
    }
    """
    # This would need an endpoint - for now, add exercises manually to database
    print(f"\n⚠️  Note: You'll need to add workout exercises to the database manually")
    print(f"User ID: {user_id}")
    print("Workouts:")
    for letter, exercises in workouts.items():
        print(f"  Workout {letter}:")
        for idx, (exercise, notes) in enumerate(exercises, 1):
            print(f"    {idx}. {exercise}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python create_dashboard_user.py <user_id> <username>")
        print("\nExample:")
        print("  python create_dashboard_user.py 123456789 JohnDoe")
        sys.exit(1)
    
    user_id = sys.argv[1]
    username = sys.argv[2]
    
    create_dashboard_member(user_id, username)
