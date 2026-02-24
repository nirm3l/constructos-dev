from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from features.bootstrap.api import router as bootstrap_router
from features.debug.api import router as debug_router
from features.licensing.api import router as licensing_router
from features.licensing.sync import (
    assert_license_startup_write_access,
    start_license_sync_worker,
    stop_license_sync_worker,
)
from features.notifications.api import router as notifications_router
from features.project_templates.api import router as project_templates_router
from features.project_skills.api import router as project_skills_router
from features.projects.api import router as projects_router
from features.rules.api import router as rules_router
from features.specifications.api import router as specifications_router
from features.tasks.api import router as tasks_router
from features.task_groups.api import router as task_groups_router
from features.users.api import router as users_router
from features.views.api import router as views_router
from features.agents.api import router as agents_router
from features.attachments.api import router as attachments_router
from features.notes.api import router as notes_router
from features.note_groups.api import router as note_groups_router
from features.support.api import router as support_router
from features.chat.api import router as chat_router
from features.support.outbox import start_bug_report_outbox_worker, stop_bug_report_outbox_worker
from features.agents.runner import start_automation_runner, stop_automation_runner
from shared.core import bootstrap_data, start_projection_worker, startup_bootstrap, stop_projection_worker
from shared.deps import is_license_write_allowed
from shared.eventing_graph import start_graph_projection_worker, stop_graph_projection_worker
from shared.eventing_vector import start_vector_projection_worker, stop_vector_projection_worker
from shared.knowledge_graph import close_knowledge_graph_driver
from shared.models import SessionLocal
from shared.persistent_subscriptions import ensure_persistent_subscriptions
from shared.realtime import register_realtime_session_hooks
from shared.settings import AGENT_RUNNER_ENABLED
from shared.system_notifications_worker import start_system_notifications_worker, stop_system_notifications_worker

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin.strip()]
register_realtime_session_hooks(SessionLocal)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup_bootstrap()
    assert_license_startup_write_access()
    ensure_persistent_subscriptions()
    start_projection_worker()
    start_graph_projection_worker()
    start_vector_projection_worker()
    start_license_sync_worker()
    start_bug_report_outbox_worker()
    start_system_notifications_worker()
    if AGENT_RUNNER_ENABLED:
        start_automation_runner()
    yield
    if AGENT_RUNNER_ENABLED:
        stop_automation_runner()
    stop_system_notifications_worker()
    stop_bug_report_outbox_worker()
    stop_license_sync_worker()
    stop_vector_projection_worker()
    stop_graph_projection_worker()
    stop_projection_worker()
    close_knowledge_graph_driver()


app = FastAPI(title="m4tr1x (CQRS + Event Sourcing + Vertical Slice)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_ORIGINS != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_license_write_access(request: Request, call_next):
    allowed, payload = is_license_write_allowed(request)
    if allowed:
        return await call_next(request)
    return JSONResponse(
        status_code=402,
        content={
            "detail": "License expired. Write access is disabled until subscription is reactivated.",
            "license": {
                "status": payload.get("status") if payload else "unlicensed",
                "write_access": bool(payload.get("write_access")) if payload else False,
                "enforcement_enabled": bool(payload.get("enforcement_enabled")) if payload else True,
                "trial_ends_at": payload.get("trial_ends_at") if payload else None,
                "grace_ends_at": payload.get("grace_ends_at") if payload else None,
            },
        },
    )

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


app.include_router(bootstrap_router)
app.include_router(users_router)
app.include_router(project_templates_router)
app.include_router(project_skills_router)
app.include_router(projects_router)
app.include_router(rules_router)
app.include_router(specifications_router)
app.include_router(tasks_router)
app.include_router(task_groups_router)
app.include_router(notes_router)
app.include_router(note_groups_router)
app.include_router(attachments_router)
app.include_router(notifications_router)
app.include_router(views_router)
app.include_router(agents_router)
app.include_router(chat_router)
app.include_router(debug_router)
app.include_router(licensing_router)
app.include_router(support_router)
