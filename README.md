# TTM Metrics API

FastAPI-based REST API for Three Target Method fitness tracking and gamification.

## Features

- ✅ PR (Personal Record) logging and tracking
- ✅ Workout plan management
- ✅ Deload counter automation
- ✅ XP and leveling system
- ✅ Core foods tracking
- ✅ Dashboard member management
- ✅ Auto-generated API documentation (Swagger UI)
- ✅ PostgreSQL database
- ✅ Type-safe with Pydantic validation

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up Database

**Option A: Use Railway Postgres (Recommended)**

1. Create a new Postgres database on Railway
2. Copy the `DATABASE_URL` from Railway dashboard
3. Create `.env` file:
```bash
DATABASE_URL=postgresql://user:password@host:port/database
```

**Option B: Local Postgres (Docker)**

```bash
docker run --name ttm-postgres -e POSTGRES_PASSWORD=password -e POSTGRES_DB=ttm_metrics -p 5432:5432 -d postgres:15
```

Then create `.env`:
```bash
DATABASE_URL=postgresql://postgres:password@localhost:5432/ttm_metrics
```

### 3. Initialize Database

```bash
python database.py
```

This creates all tables.

### 4. Run the API

```bash
uvicorn main:app --reload
```

API will be available at: `http://localhost:8000`

### 5. View API Documentation

Open your browser to:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## API Endpoints

### PRs (Personal Records)

**Log a PR:**
```bash
POST /api/prs
{
  "user_id": "user123",
  "username": "Dan",
  "exercise": "Bench Press",
  "weight": 225,
  "reps": 8
}
```

**Get user's PR history:**
```bash
GET /api/prs/{user_id}
GET /api/prs/{user_id}?exercise=Bench%20Press
```

**Get best PR for an exercise:**
```bash
GET /api/prs/{user_id}/best/{exercise}
```

### Workouts

**Create workout plan:**
```bash
POST /api/workouts
{
  "user_id": "user123",
  "workout_letter": "A",
  "exercises": [
    {
      "exercise_order": 1,
      "exercise_name": "Bench Press",
      "setup_notes": "Grip width: shoulder width",
      "special_logging": null
    }
  ]
}
```

**Get workout plan:**
```bash
GET /api/workouts/{user_id}/{workout_letter}
```

**Mark workout complete:**
```bash
POST /api/workouts/complete
{
  "user_id": "user123",
  "workout_letter": "A"
}
```

**Get deload status:**
```bash
GET /api/workouts/{user_id}/deload-status
```

### XP & Levels

**Award XP:**
```bash
POST /api/xp/award
{
  "user_id": "user123",
  "username": "Dan",
  "xp_amount": 50,
  "reason": "pr"
}
```

**Get user XP:**
```bash
GET /api/xp/{user_id}
```

### Dashboard Members

**Create dashboard member:**
```bash
POST /api/dashboard/members
{
  "user_id": "user123",
  "username": "Dan"
}
```

Returns unique dashboard code.

**Get member by code:**
```bash
GET /api/dashboard/members/{unique_code}
```

### Dashboard Endpoints (For Web Dashboard)

**Get user's workouts:**
```bash
GET /api/dashboard/{unique_code}/workouts
```
Returns user's workout program organized by letter (A, B, etc.)

**Get best PRs:**
```bash
GET /api/dashboard/{unique_code}/best-prs
```
Returns best PR for each exercise in format: `{"Squat": "315/5", "Bench Press": "225/8"}`

**Get deload status:**
```bash
GET /api/dashboard/{unique_code}/deload-status
```
Returns completion count for each workout: `{"A": 4, "B": 5}`

**Log workout:**
```bash
POST /api/dashboard/{unique_code}/log-workout
{
  "workout_letter": "A",
  "exercises": [
    {"name": "Squat", "weight": 315, "reps": 5},
    {"name": "Bench Press", "weight": 225, "reps": 8}
  ],
  "core_foods": true
}
```

**Get core foods (last 7 days):**
```bash
GET /api/dashboard/{unique_code}/core-foods
```

### Core Foods

**Log core foods:**
```bash
POST /api/core-foods
{
  "user_id": "user123",
  "date": "2026-02-05",
  "completed": true
}
```

## Testing the API

### Using Swagger UI (Easiest)

1. Start the API: `uvicorn main:app --reload`
2. Open: http://localhost:8000/docs
3. Click "Try it out" on any endpoint
4. Fill in the request body
5. Click "Execute"

### Using curl

**Log a PR:**
```bash
curl -X POST "http://localhost:8000/api/prs" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "dan_001",
    "username": "Dan",
    "exercise": "Bench Press",
    "weight": 225,
    "reps": 8
  }'
```

**Get best PR:**
```bash
curl "http://localhost:8000/api/prs/dan_001/best/Bench%20Press"
```

### Using Python requests

```python
import requests

# Log a PR
response = requests.post("http://localhost:8000/api/prs", json={
    "user_id": "dan_001",
    "username": "Dan",
    "exercise": "Bench Press",
    "weight": 225,
    "reps": 8
})

print(response.json())
# Returns: {"id": 1, "is_new_pr": true, "estimated_1rm": 284.925, ...}
```

## Database Schema

### Metrics Tables (Core Data)
- `prs` - Exercise PRs with weight, reps, estimated 1RM
- `workouts` - Workout plans for each member
- `workout_completions` - Deload counter tracking
- `core_foods_log` - Daily nutrition check-ins

### Game Tables (Gamification)
- `user_xp` - XP totals and levels
- `weekly_logs` - Weekly training log submissions
- `core_foods_checkins` - Discord check-ins (for bot compatibility)

### Dashboard Tables
- `dashboard_members` - Members with unique access codes

## Deployment to Railway

### 1. Create Railway Project

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Initialize project
railway init
```

### 2. Add Postgres

In Railway dashboard:
1. Click "New" → "Database" → "PostgreSQL"
2. Railway automatically sets `DATABASE_URL` environment variable

### 3. Deploy API

```bash
# Link to Railway project
railway link

# Deploy
railway up
```

### 4. Initialize Database on Railway

```bash
# Run migrations via Railway CLI
railway run python database.py
```

### 5. Get Your API URL

Railway will provide a public URL like:
```
https://ttm-api-production.up.railway.app
```

Your API docs will be at:
```
https://ttm-api-production.up.railway.app/docs
```

## Project Structure

```
ttm_api/
├── main.py              # FastAPI application and routes
├── database.py          # SQLAlchemy models and DB connection
├── schemas.py           # Pydantic schemas for validation
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variable template
└── README.md           # This file
```

## Key Features

### Automatic PR Detection

When logging a PR, the API automatically:
1. Calculates estimated 1RM using Epley formula
2. Checks if it's better than previous best
3. Awards 50 XP if it's a new PR
4. Returns `is_new_pr: true/false` flag

### Deload Counter

Tracks workout completions:
- Increments counter each time workout is completed
- Shows `needs_deload: true` at 6/6
- Automatically resets to 0/6 if 7+ days pass without any workout

### XP & Leveling

- Level 1 → 2: 500 XP
- Level 2 → 3: 750 XP
- Level 3 → 4: 1000 XP
- Pattern: 250 + (level × 250)

### Type Safety

All requests/responses are validated with Pydantic:
- Invalid data returns clear error messages
- Type hints throughout codebase
- Auto-generated OpenAPI schema

## Next Steps

1. **Test locally** - Use Swagger UI to test all endpoints
2. **Deploy to Railway** - Get it running in production
3. **Update Discord bot** - Call API instead of direct DB access
4. **Update Dashboard** - Call API instead of direct DB access

## Setting Up Dashboard Users

### 1. Create Dashboard Member

Use the helper script:
```bash
python create_dashboard_user.py <user_id> <username>
```

Example:
```bash
python create_dashboard_user.py 123456789 JohnDoe
```

This generates a unique access code for the user.

### 2. Add Workout Plan

Use the helper script:
```bash
python add_workout_plan.py <user_id>
```

Or manually add exercises to the database. Edit `add_workout_plan.py` to customize the program.

### 3. Share Dashboard Link

Give the user:
- Dashboard URL: https://dashboard-production-79f2.up.railway.app
- Their unique access code

They enter the code to access their personalized dashboard.

## Support

Built for the Three Target Method fitness coaching program.

For issues or questions, check the API documentation at `/docs`.
