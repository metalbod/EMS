import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# payroll_calc import moved to routers/payroll.py (only used there now).

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

# DEFAULT_OB_TEMPLATES / seed_ob_templates moved to core/onboarding_seed.py,
# used by routers/institutions.py directly (not through main.py, avoiding a
# circular import) and by core/seed.py's init_db_seed (imported near the top
# of this file) for app-startup seeding.

# Login rate limiting moved to routers/auth.py.

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
