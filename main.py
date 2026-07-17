import os
import logging
import time

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response

try:
    from db import get_db, get_admin_db
except ImportError:
    from ems.db import get_db, get_admin_db

# payroll_calc import moved to routers/payroll.py (only used there now).

try:
    from core.deps import hash_password, verify_password
    from core.onboarding_seed import seed_ob_templates
    from core.schemas import HealthResponse
    from core.tasks import app as celery_app
    from routers.audit import router as audit_router
    from routers.tasks import router as tasks_router
    from routers.notifications import router as notifications_router
    from routers.institutions import router as institutions_router
    from routers.orgchart import router as orgchart_router
    from routers.holidays import router as holidays_router
    from routers.hr_notes import router as hr_notes_router
    from routers.users import router as users_router
    from routers.leave import router as leave_router
    from routers.projects import router as projects_router
    from routers.timesheets import router as timesheets_router
    from routers.recruitment import router as recruitment_router
    from routers.onboarding import router as onboarding_router
    from routers.ld import router as ld_router
    from routers.dashboard import router as dashboard_router
    from routers.payroll import router as payroll_router
    from routers.performance import router as performance_router
    from routers.employees import router as employees_router
    from routers.auth import router as auth_router
    from routers.meta import router as meta_router
    from routers.frontend import router as frontend_router, STATIC_DIR
except ImportError:
    from ems.core.deps import hash_password, verify_password
    from ems.core.onboarding_seed import seed_ob_templates
    from ems.core.schemas import HealthResponse
    from ems.core.tasks import app as celery_app
    from ems.routers.audit import router as audit_router
    from ems.routers.tasks import router as tasks_router
    from ems.routers.notifications import router as notifications_router
    from ems.routers.institutions import router as institutions_router
    from ems.routers.orgchart import router as orgchart_router
    from ems.routers.holidays import router as holidays_router
    from ems.routers.hr_notes import router as hr_notes_router
    from ems.routers.users import router as users_router
    from ems.routers.leave import router as leave_router
    from ems.routers.projects import router as projects_router
    from ems.routers.timesheets import router as timesheets_router
    from ems.routers.recruitment import router as recruitment_router
    from ems.routers.onboarding import router as onboarding_router
    from ems.routers.ld import router as ld_router
    from ems.routers.dashboard import router as dashboard_router
    from ems.routers.payroll import router as payroll_router
    from ems.routers.performance import router as performance_router
    from ems.routers.employees import router as employees_router
    from ems.routers.auth import router as auth_router
    from ems.routers.meta import router as meta_router
    from ems.routers.frontend import router as frontend_router, STATIC_DIR

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
# Config
# ---------------------------------------------------------------------------
# JWT/auth config and the fail-fast JWT_SECRET check now live in
# core/deps.py (imported below) — the first piece extracted out of this
# file as part of splitting main.py into routers. See core/deps.py's
# docstring and the repo's tech-debt notes.

# ROLES moved to core/roles.py; INSTITUTION_ROLES/ROLE_LABELS/PLANS/
# PLAN_LABELS moved to core/constants.py — only routers/meta.py uses them now.

# RACES/RELIGIONS/GENDERS/MARITAL_STATUSES/EMPLOYMENT_TYPES/STATUSES/BANKS
# moved to core/constants.py — routers/employees.py and routers/meta.py
# need them.

# OB_ROLES moved to routers/onboarding.py (only used there now).

# DEFAULT_OB_TEMPLATES / seed_ob_templates moved to core/onboarding_seed.py
# (imported near the top of this file) so routers/institutions.py can use it
# without importing from main.py and creating a circular import.

# hash_password, verify_password imported from core.deps above.

# Login rate limiting moved to routers/auth.py.

# ---------------------------------------------------------------------------
# App + OpenAPI + CORS
# ---------------------------------------------------------------------------
app = FastAPI(
    title="EMS Multi-Tenant",
    description="Employee Management System: multi-tenant HR platform with employees, recruitment, L&D, leave, timesheets, payroll, and performance management.",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
app.include_router(audit_router)
app.include_router(notifications_router)
app.include_router(institutions_router)
app.include_router(orgchart_router)
app.include_router(holidays_router)
app.include_router(hr_notes_router)
app.include_router(users_router)
app.include_router(leave_router)
app.include_router(projects_router)
app.include_router(timesheets_router)
app.include_router(recruitment_router)
app.include_router(onboarding_router)
app.include_router(ld_router)
app.include_router(dashboard_router)
app.include_router(payroll_router)
app.include_router(performance_router)
app.include_router(employees_router)
app.include_router(auth_router)
app.include_router(meta_router)
app.include_router(tasks_router)

@app.api_route("/health", methods=["GET", "HEAD"], response_model=HealthResponse, tags=["health"])
def health():
    """Liveness/readiness probe for Fly.io — confirms the process is up and the DB pool can serve a connection.

    Supports both GET (returns JSON) and HEAD (returns status code only) for monitoring services.
    HEAD requests are used by UptimeRobot free plan and other lightweight health checks.
    """
    try:
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(503, f"unhealthy: {e}")

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Max-Age": "86400",
}

@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return Response(status_code=200, headers=CORS_HEADERS)
    response = await call_next(request)
    for k, v in CORS_HEADERS.items():
        response.headers[k] = v
    return response

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Logs every request (method, path, status, duration) and guarantees
    unhandled exceptions are logged with a stack trace before propagating —
    previously an unhandled error anywhere in an endpoint had no log trail
    at all beyond uvicorn's bare access line."""
    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        logger.exception("Unhandled error on %s %s (%sms)", request.method, request.url.path, duration_ms)
        raise
    duration_ms = round((time.monotonic() - start) * 1000, 1)
    level = logging.WARNING if response.status_code >= 500 else logging.INFO
    logger.log(level, "%s %s -> %s (%sms)", request.method, request.url.path, response.status_code, duration_ms)
    return response

# ---------------------------------------------------------------------------
# Database (Postgres/Supabase — see db.py)
# ---------------------------------------------------------------------------
# Schema is now managed by Alembic migrations (migrations/versions/).
# Database initialization happens via `alembic upgrade head` at app boot or
# deployment time. Seeding (superadmin user, OB templates) still happens
# here to decouple seed data from DDL migrations.
# ---------------------------------------------------------------------------

def _init_db_seed():
    """Initialize seed data: superadmin user and OB templates.

    This is called after the schema is created (either via Alembic or on
    fresh app boot when no schema yet exists). Does not run any DDL — only
    INSERT and UPDATE statements for seed data.
    """
    conn = get_admin_db()
    try:
        # Seed platform superadmin. must_change_password=1 forces a password
        # rotation before anything else meaningful can happen with this
        # well-known default credential — see routers/auth.py's login response
        # and routers/users.py's update_user, which clears the flag once a real
        # password is set.
        if not conn.execute("SELECT id FROM users WHERE role='superadmin' LIMIT 1").fetchone():
            conn.execute("""
                INSERT INTO users (institution_id, username, full_name, email, password_hash, role, must_change_password)
                VALUES (NULL, ?, ?, ?, ?, 'superadmin', 1)
            """, ("superadmin", "Platform Administrator", "admin@platform.com", hash_password("Admin@123")))
            conn.commit()

        # One-time backfill for superadmin accounts seeded before
        # must_change_password existed: if the password still matches the known
        # default, flag it for rotation now instead of leaving it silently
        # unrotated forever. Skips accounts that already changed their password
        # (verify_password against the old default correctly fails for those).
        for row in conn.execute(
            "SELECT id, password_hash FROM users WHERE role='superadmin' AND must_change_password=0"
        ).fetchall():
            if verify_password("Admin@123", row["password_hash"]):
                conn.execute("UPDATE users SET must_change_password=1 WHERE id=?", (row["id"],))
        conn.commit()

        # Seed OB templates for existing institutions that don't have them
        inst_ids = [r[0] for r in conn.execute("SELECT id FROM institutions").fetchall()]
        for iid in inst_ids:
            seed_ob_templates(conn, iid)
        if inst_ids:
            conn.commit()
    finally:
        conn.close()

_init_db_seed()

# make_token, decode_token, get_current_user, require_roles, need_inst
# imported from core.deps above.

# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------
# write_audit moved to core/audit.py (imported near the top of this file)
# since routers/performance.py needs it too and routers must not import
# from main.py.

# SENSITIVE/FIELD_LABELS/diff_employee/write_employee_change_note moved to
# routers/employees.py (Employee-only).

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
# InstitutionIn/InstitutionUpdate/InstStatusIn moved to routers/institutions.py.
# MAX_LOGO_DATA_URL_LEN / logo_url validation moved to core/validators.py.

# EmployeeIn/BulkUploadIn/StatusUpdate moved to routers/employees.py.

# LoginIn/SwitchRoleIn moved to routers/auth.py.

# UserIn/UserUpdate moved to routers/users.py.

# OBTemplateIn/OBChecklistStartIn/OBItemUpdateIn/OBItemEditIn/OBItemAddIn
# moved to routers/onboarding.py.

# LDCourseIn/LDEnrollIn/LDEnrollStatusIn/LDQuizOptionIn/LDQuizQuestionIn/
# LDQuizIn/LDQuizAttemptIn/LDModuleIn/LDModulesIn moved to routers/ld.py.

# LeaveTypeIn/LeaveBalanceAdjustIn/LeaveApplicationIn/LeaveStatusIn moved to
# routers/leave.py.

# ProjectIn/ProjectTaskIn/TaskAssignmentIn/TaskOpenToAllIn moved to
# routers/projects.py.

# PayrollRunIn/PayslipAdjustIn moved to routers/payroll.py.

# PerformanceCycleIn/GoalIn/KeyResultIn/SelfReviewIn/ManagerReviewIn/
# CalibrateIn/GoalUpdateIn/MeritIncrementIn/BonusPayoutIn moved to
# routers/performance.py.

# TimesheetEntryIn/TimesheetStartIn/TimesheetStatusIn moved to
# routers/timesheets.py.

# gen_employee_id moved to routers/employees.py.

# Auth routes (login, switch-role, me) now live in routers/auth.py,
# mounted above via app.include_router(auth_router).

# /api/meta now lives in routers/meta.py, mounted above via
# app.include_router(meta_router).

# Institution CRUD routes now live in routers/institutions.py, mounted
# above via app.include_router(institutions_router).

# Employee routes (list/create/get/update/status), CAN_WRITE/CAN_TOGGLE,
# and Bulk Employee Upload now live in routers/employees.py, mounted above
# via app.include_router(employees_router).

# Org chart routes now live in routers/orgchart.py, mounted above via
# app.include_router(orgchart_router).

# Audit log routes now live in routers/audit.py, mounted below via
# app.include_router(audit_router).

# User management routes now live in routers/users.py, mounted above via
# app.include_router(users_router).

# HR Notes routes now live in routers/hr_notes.py, mounted above via
# app.include_router(hr_notes_router).

# ---------------------------------------------------------------------------
# Recruitment — models
# ---------------------------------------------------------------------------
# Recruitment models/constants/helpers/routes now live in
# routers/recruitment.py, mounted above via app.include_router(recruitment_router).

# _log_ob / _log_ld / _auto_enroll_ld_course / _complete_linked_ob_items
# moved to core/ob_ld_shared.py (imported near the top of this file) since
# they're needed by both the not-yet-extracted L&D routes below and
# routers/onboarding.py.

# _log_leave / _compute_leave_days / _get_or_create_leave_balance moved to
# routers/leave.py (only used by the Leave routes now mounted there).

# _log_timesheet moved to routers/timesheets.py (only used there now).

# _get_candidate / _get_req / _gen_offer_letter and all Recruitment routes
# now live in routers/recruitment.py.

# Onboarding/Offboarding Template and Checklist routes now live in
# routers/onboarding.py, mounted above via app.include_router(onboarding_router).

# related-contracts / rehire-prefill routes now live in routers/employees.py.

# /api/employees/{employee_id}/ob-history now lives in routers/onboarding.py.

# Learning & Development (Courses, Enrollments, Quizzes, Course Modules)
# routes now live in routers/ld.py, mounted above via app.include_router(ld_router).

# Holiday Manager routes now live in routers/holidays.py, mounted above via
# app.include_router(holidays_router). LEAVE_MANAGE_ROLES (still needed by
# the Leave routes below) now lives in core/roles.py, imported near the top
# of this file.

# Leave — Types / Balances / Applications routes now live in
# routers/leave.py, mounted above via app.include_router(leave_router).

# Projects / Project Tasks / Task Assignments routes now live in
# routers/projects.py, mounted above via app.include_router(projects_router).

# Institution/System-Wide Notification routes now live in routers/notifications.py,
# mounted above via app.include_router(notifications_router).

# Dashboard To-Do List routes now live in routers/dashboard.py, mounted
# above via app.include_router(dashboard_router).

# Timesheets routes now live in routers/timesheets.py, mounted above via
# app.include_router(timesheets_router).

# Payroll routes now live in routers/payroll.py, mounted above via
# app.include_router(payroll_router). PAYROLL_VIEW_ROLES (still needed by
# the Performance routes below) now lives in core/roles.py, imported near
# the top of this file.

# Performance (Cycles, Goals, Appraisals, Performance->Payroll integration)
# routes now live in routers/performance.py, mounted above via
# app.include_router(performance_router).

# ---------------------------------------------------------------------------
# Frontend — static mount stays here (APIRouter has no .mount()); the SPA
# catch-all route itself lives in routers/frontend.py and is included last,
# below, after every API router so it can't shadow a more specific route.
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(frontend_router)
