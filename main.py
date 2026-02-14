"""
TTM Metrics API - FastAPI application
Handles all PR logging, workout tracking, and XP management
"""

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import datetime, timedelta
import secrets
import re
import os

from database import (
    get_db, init_db, PR, Workout, WorkoutCompletion, UserXP,
    DashboardMember, CoreFoodsLog as CoreFoodsLogModel, WeeklyLog,
    CoreFoodsCheckin, UserNote, ExerciseSwap, WorkoutSession,
    SessionLocal
)
from schemas import (
    PRCreate, PRResponse, BestPRResponse,
    WorkoutPlanCreate, WorkoutCompletionUpdate, DeloadStatus,
    XPAward, XPResponse,
    DashboardMemberCreate, DashboardMemberResponse,
    CoreFoodsLog
)
from config import XP_REWARDS_API, XP_ENABLED
from admin_dump import router as admin_dump_router
from admin_rebuild import router as admin_rebuild_router
from admin_core_foods import router as admin_core_foods_router

app = FastAPI(
    title="TTM Metrics API",
    description="Three Target Method - Fitness tracking and gamification API",
    version="1.5.7"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_dump_router)
app.include_router(admin_rebuild_router)
app.include_router(admin_core_foods_router)
