from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from features.bootstrap.api import router as bootstrap_router
from features.debug.api import router as debug_router
from features.notifications.api import router as notifications_router
from features.projects.api import router as projects_router
from features.tasks.api import router as tasks_router
from features.users.api import router as users_router
from features.views.api import router as views_router
from shared.core import bootstrap_data, project_kurrent_events_once, start_projection_worker, startup_bootstrap, stop_projection_worker

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup_bootstrap()
    project_kurrent_events_once(limit=5000)
    start_projection_worker()
    yield
    stop_projection_worker()


app = FastAPI(title="Task Management (CQRS + Event Sourcing + Vertical Slice)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_ORIGINS != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


app.include_router(bootstrap_router)
app.include_router(users_router)
app.include_router(projects_router)
app.include_router(tasks_router)
app.include_router(notifications_router)
app.include_router(views_router)
app.include_router(debug_router)
