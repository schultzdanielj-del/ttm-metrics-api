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

app = FastAPI(
    title="TTM Metrics API",
    description="Three Target Method - Fitness tracking and gamification API",
    version="1.5.2"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_dump_router)


@app.on_event("startup")
def startup_event():
    init_db()


@app.get("/")
def root():
    return {"status": "healthy", "service": "TTM Metrics API", "version": "1.5.2"}
