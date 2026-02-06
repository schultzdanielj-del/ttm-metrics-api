"""
Quick test script for TTM API
Run this after starting the API to verify it's working
"""

import requests
import json

BASE_URL = "http://localhost:8000"

def test_health():
    """Test health check endpoint"""
    print("\n=== Testing Health Check ===")
    response = requests.get(f"{BASE_URL}/")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    assert response.status_code == 200
    print("✅ Health check passed")


def test_log_pr():
    """Test logging a PR"""
    print("\n=== Testing Log PR ===")
    pr_data = {
        "user_id": "test_user_001",
        "username": "Test User",
        "exercise": "Bench Press",
        "weight": 225,
        "reps": 8
    }
    
    response = requests.post(f"{BASE_URL}/api/prs", json=pr_data)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    assert response.status_code == 200
    assert response.json()["is_new_pr"] == True
    print("✅ PR logged successfully")
    return response.json()


def test_get_best_pr(user_id, exercise):
    """Test getting best PR"""
    print("\n=== Testing Get Best PR ===")
    response = requests.get(f"{BASE_URL}/api/prs/{user_id}/best/{exercise}")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    assert response.status_code == 200
    print("✅ Best PR retrieved")


def test_create_workout():
    """Test creating a workout plan"""
    print("\n=== Testing Create Workout Plan ===")
    workout_data = {
        "user_id": "test_user_001",
        "workout_letter": "A",
        "exercises": [
            {
                "exercise_order": 1,
                "exercise_name": "Bench Press",
                "setup_notes": "Grip width: shoulder width",
                "special_logging": None
            },
            {
                "exercise_order": 2,
                "exercise_name": "Incline DB Press",
                "setup_notes": None,
                "special_logging": None
            }
        ]
    }
    
    response = requests.post(f"{BASE_URL}/api/workouts", json=workout_data)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    assert response.status_code == 200
    print("✅ Workout plan created")


def test_complete_workout():
    """Test marking workout as complete"""
    print("\n=== Testing Workout Completion ===")
    completion_data = {
        "user_id": "test_user_001",
        "workout_letter": "A"
    }
    
    response = requests.post(f"{BASE_URL}/api/workouts/complete", json=completion_data)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    assert response.status_code == 200
    print("✅ Workout marked complete")


def test_get_xp(user_id):
    """Test getting user XP"""
    print("\n=== Testing Get XP ===")
    response = requests.get(f"{BASE_URL}/api/xp/{user_id}")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    assert response.status_code == 200
    print("✅ XP retrieved")


def run_all_tests():
    """Run all tests in sequence"""
    print("\n" + "="*50)
    print("TTM API Test Suite")
    print("="*50)
    
    try:
        test_health()
        pr_result = test_log_pr()
        test_get_best_pr(pr_result["user_id"], pr_result["exercise"])
        test_create_workout()
        test_complete_workout()
        test_get_xp("test_user_001")
        
        print("\n" + "="*50)
        print("✅ ALL TESTS PASSED!")
        print("="*50)
        print("\nYour API is working correctly!")
        print(f"View API docs at: {BASE_URL}/docs")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        print("\nMake sure:")
        print("1. API is running: uvicorn main:app --reload")
        print("2. Database is initialized: python database.py")
        print("3. DATABASE_URL is set correctly in .env")


if __name__ == "__main__":
    run_all_tests()
