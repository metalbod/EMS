import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core.seed import init_db_seed
from core.middleware import cors_middleware, request_logging_middleware
from core.tasks import app as celery_app
from routers.audit import router as audit_router
from routers.tasks import router as tasks_router
from routers.notifications import router as notifications_router
from routers.institutions import router as institutions_router
from routers.orgchart import router as orgchart_router
from routers.holidays import router as holidays_router
from routers.hr_notes import router as hr_notes_router
from routers.users import router as users_router
from routers.roles import router as roles_router
from routers.leave import router as leave_router
from routers.approval_workflow_settings import router as approval_workflow_router
from routers.projects import router as projects_router
from routers.timesheets import router as timesheets_router
from routers.overtime import router as overtime_router
from routers.resignation import router as resignation_router
from routers.recruitment import router as recruitment_router
from routers.onboarding import router as onboarding_router
from routers.ld import router as ld_router
from routers.dashboard import router as dashboard_router
from routers.payroll import router as payroll_router
from routers.performance import router as performance_router
from routers.employees import router as employees_router
from routers.employee_documents import router as employee_documents_router
from routers.locations import router as locations_router
from routers.location_features import router as location_features_router
from routers.location_phase2 import router as location_phase2_router
from routers.compensation_pay_structure import router as compensation_pay_structure_router
from routers.compensation_merit import router as compensation_merit_router
from routers.compensation_bonus import router as compensation_bonus_router
from routers.compensation_commission import router as compensation_commission_router
from routers.compensation_equity import router as compensation_equity_router
from routers.compensation_rewards import router as compensation_rewards_router
from routers.benefits import router as benefits_router
from routers.attendance import router as attendance_router
from routers.fr_integration import router as fr_integration_router
from routers.assistant import router as assistant_router
from routers.auth import router as auth_router
from routers.meta import router as meta_router
from routers.health import router as health_router
from routers.frontend import router as frontend_router, STATIC_DIR

# ---------------------------------------------------------------------------
# Logging — plain stdout logging so `fly logs` / any container log collector
# picks it up. PYTHONUNBUFFERED=1 (set in the Dockerfile) keeps it flushing
# immediately instead of buffering.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("ems")

# ---------------------------------------------------------------------------
# Error tracking (Sentry)
# ---------------------------------------------------------------------------
sentry_dsn = os.environ.get("SENTRY_DSN")
if sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[FastApiIntegration()],
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        profiles_sample_rate=float(os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0.01")),
        environment=os.environ.get("ENVIRONMENT", "development"),
    )

# ---------------------------------------------------------------------------
# App + OpenAPI + CORS
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Seed initial data (superadmin user, OB templates) on app startup.

    Schema migrations are applied separately via `alembic upgrade head`
    (run manually / in CI before deploy) — NOT here. An earlier version of
    this hook shelled out to `alembic upgrade head` synchronously, which
    blocks the asyncio event loop for the full subprocess duration since
    startup handlers run directly on the loop, not in a thread. That call
    could hang indefinitely on lock contention with a concurrent migration
    run, keeping uvicorn from ever accepting connections — do not
    reintroduce it here.
    """
    try:
        init_db_seed()
    except Exception as e:
        logger.error(f"Error seeding database: {e}")
    yield

app = FastAPI(
    title="EMS Multi-Tenant",
    description="Employee Management System: multi-tenant HR platform with employees, recruitment, L&D, leave, timesheets, payroll, and performance management.",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# Registration order matters: matches the original @app.middleware decorator
# order this was extracted from (core/middleware.py) — cors_middleware first,
# request_logging_middleware second.
app.middleware("http")(cors_middleware)
app.middleware("http")(request_logging_middleware)

app.include_router(audit_router)
app.include_router(notifications_router)
app.include_router(institutions_router)
app.include_router(orgchart_router)
app.include_router(holidays_router)
app.include_router(hr_notes_router)
app.include_router(users_router)
app.include_router(roles_router)
app.include_router(leave_router)
app.include_router(approval_workflow_router)
app.include_router(projects_router)
app.include_router(timesheets_router)
app.include_router(overtime_router)
app.include_router(resignation_router)
app.include_router(recruitment_router)
app.include_router(onboarding_router)
app.include_router(ld_router)
app.include_router(dashboard_router)
app.include_router(payroll_router)
app.include_router(performance_router)
app.include_router(employees_router)
app.include_router(employee_documents_router)
app.include_router(locations_router)
app.include_router(location_features_router)
app.include_router(location_phase2_router)
app.include_router(compensation_pay_structure_router)
app.include_router(compensation_merit_router)
app.include_router(compensation_bonus_router)
app.include_router(compensation_commission_router)
app.include_router(compensation_equity_router)
app.include_router(compensation_rewards_router)
app.include_router(benefits_router)
app.include_router(attendance_router)
app.include_router(fr_integration_router)
app.include_router(assistant_router)
app.include_router(auth_router)
app.include_router(meta_router)
app.include_router(tasks_router)
app.include_router(health_router)

# ---------------------------------------------------------------------------
# Database (Postgres/Supabase — see db.py)
# ---------------------------------------------------------------------------
# Schema is managed by Alembic migrations (migrations/versions/), applied
# separately (run manually / in CI before deploy). Seed data (superadmin
# user, OB templates) is decoupled from DDL migrations — see core/seed.py's
# init_db_seed, called from the startup event handler above.

# ---------------------------------------------------------------------------
# Frontend — static mount stays here (APIRouter has no .mount()); the SPA
# catch-all route itself lives in routers/frontend.py and is included last,
# below, after every API router so it can't shadow a more specific route.
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(frontend_router)
