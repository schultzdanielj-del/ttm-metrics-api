#!/usr/bin/env python3
"""
Create a dashboard member - supports Discord users and non-Discord users

Usage:
    # Discord user
    python create_dashboard_user.py --discord-id 718992882182258769 --name "Dan Schultz"
    
    # Non-Discord user  
    python create_dashboard_user.py --name "John Smith"
"""

import requests
import argparse
import secrets

API_BASE_URL = "https://ttm-metrics-api-production.up.railway.app"

def create_dashboard_member(discord_id, full_name):
    """
    Create a dashboard member with unique access code
    
    Args:
        discord_id: Discord user ID (or None for non-Discord users)
        full_name: User's full name (e.g., "Dan Schultz")
    """
    # Generate user_id
    if discord_id:
        user_id = str(discord_id)
    else:
        # For non-Discord users, generate a unique ID with 'ND_' prefix
        user_id = f"ND_{secrets.token_hex(8)}"
    
    # Extract first name
    first_name = full_name.split()[0]
    
    print(f"Creating dashboard member...")
    print(f"User ID: {user_id}")
    print(f"Full Name: {full_name}")
    print(f"First Name: {first_name}")
    print()
    
    # Create dashboard member via API
    response = requests.post(
        f"{API_BASE_URL}/api/dashboard/members",
        json={
            "user_id": user_id,
            "username": first_name,  # Store first name only
            "full_name": full_name    # Store full name
        }
    )
    
    if response.status_code == 200:
        data = response.json()
        unique_code = data['unique_code']
        
        print("✅ Dashboard member created!")
        print()
        print(f"User ID: {user_id}")
        print(f"Name: {full_name}")
        print(f"First Name: {first_name}")
        print(f"Unique Code: {unique_code}")
        print()
        print(f"Dashboard URL:")
        print(f"https://dashboard-production-79f2.up.railway.app/{unique_code}")
        print()
        print("Next step: Add workout plan")
        print(f"python add_workout_plan.py {user_id}")
        
        return unique_code
    else:
        print(f"❌ Error: {response.status_code}")
        print(response.text)
        return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Create a dashboard member')
    parser.add_argument('--discord-id', type=str, help='Discord user ID (optional)')
    parser.add_argument('--name', type=str, required=True, help='Full name (e.g., "Dan Schultz")')
    
    args = parser.parse_args()
    
    create_dashboard_member(args.discord_id, args.name)
