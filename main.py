"""
TTM Metrics API - FastAPI application
Handles all PR logging, workout tracking, and XP management
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from admin_dump import router as admin_dump_router
from admin_rebuild import router as admin_rebuild_router
from admin_core_foods import router as admin_core_foods_router
from main_routes import router as main_routes_router
from main_routes_p2 import router as main_routes_p2_router
from coach_messages import router as coach_messages_router
from carousel import router as carousel_router
from coach_dashboard import router as coach_dashboard_router

app = FastAPI(
    title="TTM Metrics API",
    description="Three Target Method - Fitness tracking and gamification API",
    version="1.6.0"
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
app.include_router(main_routes_router)
app.include_router(main_routes_p2_router)
app.include_router(coach_messages_router)
app.include_router(carousel_router)
app.include_router(coach_dashboard_router)


@app.on_event("startup")
def startup_event():
    init_db()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
