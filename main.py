import os
import io
import csv
import hashlib
import json
import logging
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta, date
from typing import List, Optional

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, field_validator, ValidationError

try:
    from db import get_db, IntegrityError
except ImportError:
    from ems.db import get_db, IntegrityError

# payroll_calc import moved to routers/payroll.py (only used there now).

try:
    from core.deps import (
        hash_password, verify_password, make_token,
        get_current_user, require_roles, need_inst,
    )
    from core.onboarding_seed import seed_ob_templates
    from core.validators import validate_logo_url as _validate_logo_url
    from core.roles import ROLES, LEAVE_MANAGE_ROLES, PAYROLL_VIEW_ROLES
    from core.audit import write_audit
    from core.org_queries import subordinates_in_clause, is_self_or_subordinate
    from routers.audit import router as audit_router
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
except ImportError:
    from ems.core.deps import (
        hash_password, verify_password, make_token,
        get_current_user, require_roles, need_inst,
    )
    from ems.core.onboarding_seed import seed_ob_templates
    from ems.core.validators import validate_logo_url as _validate_logo_url
    from ems.core.roles import ROLES, LEAVE_MANAGE_ROLES, PAYROLL_VIEW_ROLES
    from ems.core.audit import write_audit
    from ems.core.org_queries import subordinates_in_clause, is_self_or_subordinate
    from ems.routers.audit import router as audit_router
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
# Config
# ---------------------------------------------------------------------------
# JWT/auth config and the fail-fast JWT_SECRET check now live in
# core/deps.py (imported below) — the first piece extracted out of this
# file as part of splitting main.py into routers. See core/deps.py's
# docstring and the repo's tech-debt notes.

# ROLES moved to core/roles.py (imported near the top of this file) since
# routers/users.py needs it too and routers must not import from main.py.
INSTITUTION_ROLES = ["hr_manager", "hr_admin", "manager", "payroll_manager", "employee"]
ROLE_LABELS = {
    "superadmin": "Platform Admin", "hr_manager": "HR Manager",
    "hr_admin": "HR Admin", "manager": "Manager", "payroll_manager": "Payroll Manager",
    "employee": "Employee",
}
PLANS = ["starter", "professional", "enterprise"]
PLAN_LABELS = {"starter": "Starter", "professional": "Professional", "enterprise": "Enterprise"}

RACES            = ["Malay","Chinese","Indian","Bumiputera Sabah","Bumiputera Sarawak","Orang Asli","Others"]
RELIGIONS        = ["Islam","Buddhism","Christianity","Hinduism","Sikhism","No Religion","Others"]
GENDERS          = ["Male","Female"]
MARITAL_STATUSES = ["Single","Married","Divorced","Widowed"]
EMPLOYMENT_TYPES = ["Permanent","Contract","Part-Time","Internship"]
STATUSES         = ["Active","Inactive"]
BANKS = [
    "Maybank","CIMB Bank","Public Bank","RHB Bank","Hong Leong Bank",
    "AmBank","Bank Islam","Bank Rakyat","Affin Bank","Alliance Bank",
    "HSBC Bank Malaysia","Standard Chartered","OCBC Bank","UOB Malaysia","Others",
]

# OB_ROLES moved to routers/onboarding.py (only used there now).

# DEFAULT_OB_TEMPLATES / seed_ob_templates moved to core/onboarding_seed.py
# (imported near the top of this file) so routers/institutions.py can use it
# without importing from main.py and creating a circular import.

# hash_password, verify_password imported from core.deps above.

# ---------------------------------------------------------------------------
# Login rate limiting — in-memory sliding window. This is intentionally
# process-local (no Redis/shared store): the app currently runs as a single
# uvicorn worker/machine, so this is a real backstop against brute-forcing a
# single username, not just decoration. If this ever runs as multiple
# workers/machines, move this to a shared store or it silently stops working
# per-instance.
# ---------------------------------------------------------------------------
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300  # 5 minutes
_login_failures: dict = defaultdict(deque)

def _login_rate_key(request: Request, username: str) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"{ip}:{username.strip().lower()}"

def _check_login_rate_limit(key: str):
    now = time.monotonic()
    attempts = _login_failures[key]
    while attempts and now - attempts[0] > LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        retry_after = max(1, int(LOGIN_WINDOW_SECONDS - (now - attempts[0])))
        raise HTTPException(429, f"Too many failed login attempts. Try again in {retry_after} seconds.")

def _record_login_failure(key: str):
    _login_failures[key].append(time.monotonic())
    logger.warning("Failed login attempt for %s (%d in window)", key, len(_login_failures[key]))

def _clear_login_failures(key: str):
    _login_failures.pop(key, None)

# ---------------------------------------------------------------------------
# App + CORS
# ---------------------------------------------------------------------------
app = FastAPI(title="EMS Multi-Tenant")
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

@app.get("/health")
def health():
    """Liveness/readiness probe for Fly.io — confirms the process is up and the DB pool can serve a connection."""
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
def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TABLE IF NOT EXISTS institutions (
            id              SERIAL  PRIMARY KEY,
            name            TEXT    NOT NULL,
            code            TEXT    NOT NULL UNIQUE,
            contact_name    TEXT,
            contact_email   TEXT    NOT NULL,
            phone           TEXT,
            address         TEXT,
            status          TEXT    NOT NULL DEFAULT 'Active',
            plan            TEXT    NOT NULL DEFAULT 'starter',
            max_employees   INTEGER NOT NULL DEFAULT 50,
            logo_url        TEXT,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        CREATE TABLE IF NOT EXISTS users (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER REFERENCES institutions(id),
            username        TEXT    NOT NULL UNIQUE,
            full_name       TEXT    NOT NULL,
            email           TEXT,
            password_hash   TEXT    NOT NULL,
            role            TEXT    NOT NULL DEFAULT 'employee',
            roles           TEXT,
            employee_id     TEXT,
            department      TEXT,
            is_active       INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            updated_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        DROP TRIGGER IF EXISTS trg_users_upd ON users;
        CREATE TRIGGER trg_users_upd BEFORE UPDATE ON users
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();

        CREATE TABLE IF NOT EXISTS employees (
            id                  SERIAL  PRIMARY KEY,
            institution_id      INTEGER NOT NULL REFERENCES institutions(id),
            employee_id         TEXT    NOT NULL,
            full_name           TEXT    NOT NULL,
            preferred_name      TEXT,
            ic_number           TEXT    NOT NULL,
            passport_number     TEXT,
            nationality         TEXT    NOT NULL DEFAULT 'Malaysian',
            race                TEXT    NOT NULL,
            religion            TEXT    NOT NULL,
            gender              TEXT    NOT NULL,
            date_of_birth       TEXT    NOT NULL,
            marital_status      TEXT    NOT NULL,
            personal_email      TEXT,
            phone               TEXT    NOT NULL,
            address             TEXT,
            department          TEXT    NOT NULL,
            designation         TEXT    NOT NULL,
            employment_type     TEXT    NOT NULL,
            start_date          TEXT    NOT NULL,
            probation_end_date  TEXT,
            contract_end_date   TEXT,
            work_email          TEXT,
            epf_number          TEXT,
            socso_number        TEXT,
            income_tax_number   TEXT,
            bank_name           TEXT,
            bank_account        TEXT,
            basic_salary        NUMERIC(12,2) NOT NULL DEFAULT 0,
            reports_to          TEXT,
            status              TEXT    NOT NULL DEFAULT 'Active',
            created_at          TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            updated_at          TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(institution_id, employee_id)
        );

        DROP TRIGGER IF EXISTS trg_employees_upd ON employees;
        CREATE TRIGGER trg_employees_upd BEFORE UPDATE ON employees
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();

        CREATE TABLE IF NOT EXISTS audit_logs (
            id                      SERIAL  PRIMARY KEY,
            institution_id          INTEGER NOT NULL,
            timestamp               TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            actor_id                INTEGER NOT NULL,
            actor_username          TEXT    NOT NULL,
            actor_role              TEXT    NOT NULL,
            target_employee_id      TEXT    NOT NULL,
            target_employee_name    TEXT    NOT NULL,
            action                  TEXT    NOT NULL,
            changes                 TEXT,
            ip_address              TEXT
        );

        CREATE TABLE IF NOT EXISTS job_requisitions (
            id                  SERIAL  PRIMARY KEY,
            institution_id      INTEGER NOT NULL REFERENCES institutions(id),
            title               TEXT    NOT NULL,
            department          TEXT    NOT NULL,
            headcount           INTEGER NOT NULL DEFAULT 1,
            employment_type     TEXT    NOT NULL DEFAULT 'Permanent',
            description         TEXT,
            requirements        TEXT,
            salary_min          NUMERIC(12,2),
            salary_max          NUMERIC(12,2),
            priority            TEXT    NOT NULL DEFAULT 'Normal',
            status              TEXT    NOT NULL DEFAULT 'Draft',
            created_by          TEXT    NOT NULL,
            approved_by         TEXT,
            approval_comments   TEXT,
            closed_at           TEXT,
            created_at          TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            updated_at          TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        DROP TRIGGER IF EXISTS trg_req_upd ON job_requisitions;
        CREATE TRIGGER trg_req_upd BEFORE UPDATE ON job_requisitions
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();

        CREATE TABLE IF NOT EXISTS candidates (
            id                      SERIAL  PRIMARY KEY,
            institution_id          INTEGER NOT NULL REFERENCES institutions(id),
            requisition_id          INTEGER REFERENCES job_requisitions(id),
            full_name               TEXT    NOT NULL,
            email                   TEXT,
            phone                   TEXT,
            ic_number               TEXT,
            nationality             TEXT    DEFAULT 'Malaysian',
            gender                  TEXT,
            date_of_birth           TEXT,
            address                 TEXT,
            current_position        TEXT,
            current_company         TEXT,
            experience_years        INTEGER DEFAULT 0,
            employment_history      TEXT,
            highest_qualification   TEXT,
            field_of_study          TEXT,
            institution_name        TEXT,
            graduation_year         INTEGER,
            certifications          TEXT,
            skills                  TEXT,
            source                  TEXT    NOT NULL DEFAULT 'Direct',
            resume_text             TEXT,
            expected_salary         NUMERIC(12,2),
            notice_period           TEXT,
            linkedin_url            TEXT,
            referral_by             TEXT,
            stage                   TEXT    NOT NULL DEFAULT 'New',
            notes                   TEXT,
            created_by              TEXT    NOT NULL,
            created_at              TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            updated_at              TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        DROP TRIGGER IF EXISTS trg_cand_upd ON candidates;
        CREATE TRIGGER trg_cand_upd BEFORE UPDATE ON candidates
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();

        CREATE TABLE IF NOT EXISTS interviews (
            id                  SERIAL  PRIMARY KEY,
            institution_id      INTEGER NOT NULL REFERENCES institutions(id),
            candidate_id        INTEGER NOT NULL REFERENCES candidates(id),
            requisition_id      INTEGER REFERENCES job_requisitions(id),
            interview_type      TEXT    NOT NULL DEFAULT 'In-Person',
            scheduled_date      TEXT    NOT NULL,
            scheduled_time      TEXT    NOT NULL,
            duration_mins       INTEGER NOT NULL DEFAULT 60,
            location            TEXT,
            interviewers        TEXT,
            status              TEXT    NOT NULL DEFAULT 'Scheduled',
            notes               TEXT,
            created_by          TEXT    NOT NULL,
            created_at          TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        CREATE TABLE IF NOT EXISTS interview_scores (
            id                      SERIAL  PRIMARY KEY,
            interview_id            INTEGER NOT NULL REFERENCES interviews(id),
            candidate_id            INTEGER NOT NULL REFERENCES candidates(id),
            institution_id          INTEGER NOT NULL,
            scored_by               TEXT    NOT NULL,
            technical_score         INTEGER,
            communication_score     INTEGER,
            attitude_score          INTEGER,
            culture_fit_score       INTEGER,
            overall_score           INTEGER,
            recommendation          TEXT    NOT NULL DEFAULT 'Maybe',
            comments                TEXT,
            created_at              TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(interview_id, scored_by)
        );

        CREATE TABLE IF NOT EXISTS offers (
            id                  SERIAL  PRIMARY KEY,
            institution_id      INTEGER NOT NULL REFERENCES institutions(id),
            candidate_id        INTEGER NOT NULL REFERENCES candidates(id),
            requisition_id      INTEGER REFERENCES job_requisitions(id),
            offer_type          TEXT    NOT NULL DEFAULT 'Offer',
            salary_offered      NUMERIC(12,2),
            start_date          TEXT,
            expiry_date         TEXT,
            status              TEXT    NOT NULL DEFAULT 'Draft',
            letter_content      TEXT,
            created_by          TEXT    NOT NULL,
            created_at          TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            updated_at          TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        DROP TRIGGER IF EXISTS trg_offer_upd ON offers;
        CREATE TRIGGER trg_offer_upd BEFORE UPDATE ON offers
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();

        CREATE TABLE IF NOT EXISTS candidate_audit_log (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            candidate_id    INTEGER NOT NULL REFERENCES candidates(id),
            action          TEXT    NOT NULL,
            detail          TEXT,
            performed_by    TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        CREATE TABLE IF NOT EXISTS ob_audit_log (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            checklist_id    INTEGER NOT NULL,
            employee_id     TEXT    NOT NULL,
            ob_type         TEXT    NOT NULL,
            action          TEXT    NOT NULL,
            detail          TEXT,
            performed_by    TEXT    NOT NULL,
            performer_role  TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        CREATE TABLE IF NOT EXISTS hr_notes (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            employee_id     TEXT    NOT NULL,
            note_type       TEXT    NOT NULL DEFAULT 'general',
            body            TEXT    NOT NULL,
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            deleted         INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS ob_templates (
            id                   SERIAL  PRIMARY KEY,
            institution_id       INTEGER NOT NULL REFERENCES institutions(id),
            type                 TEXT    NOT NULL DEFAULT 'onboarding',
            title                TEXT    NOT NULL,
            description          TEXT,
            assigned_role        TEXT    NOT NULL DEFAULT 'hr_admin',
            order_index          INTEGER NOT NULL DEFAULT 0,
            is_active            INTEGER NOT NULL DEFAULT 1,
            linked_ld_course_id  INTEGER,
            created_at           TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        CREATE TABLE IF NOT EXISTS ob_checklists (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            employee_id     TEXT    NOT NULL,
            type            TEXT    NOT NULL DEFAULT 'onboarding',
            status          TEXT    NOT NULL DEFAULT 'In Progress',
            triggered_by    TEXT    NOT NULL,
            notes           TEXT,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            completed_at    TEXT
        );

        CREATE TABLE IF NOT EXISTS ob_checklist_items (
            id                   SERIAL  PRIMARY KEY,
            checklist_id         INTEGER NOT NULL REFERENCES ob_checklists(id),
            institution_id       INTEGER NOT NULL,
            template_id          INTEGER REFERENCES ob_templates(id),
            title                TEXT    NOT NULL,
            description          TEXT,
            assigned_role        TEXT    NOT NULL DEFAULT 'hr_admin',
            order_index          INTEGER NOT NULL DEFAULT 0,
            status               TEXT    NOT NULL DEFAULT 'Pending',
            completed_by         TEXT,
            completed_at         TEXT,
            notes                TEXT,
            linked_ld_course_id  INTEGER,
            linked_ld_enrollment_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS ld_courses (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            title           TEXT    NOT NULL,
            category        TEXT    NOT NULL DEFAULT 'professional_development',
            description     TEXT,
            cost            NUMERIC(12,2) NOT NULL DEFAULT 0,
            is_active       INTEGER NOT NULL DEFAULT 1,
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        CREATE TABLE IF NOT EXISTS ld_enrollments (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            course_id       INTEGER NOT NULL REFERENCES ld_courses(id),
            employee_id     TEXT    NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'In Progress',
            requested_by    TEXT    NOT NULL,
            approved_by     TEXT,
            notes           TEXT,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            completed_at    TEXT
        );

        CREATE TABLE IF NOT EXISTS ld_audit_log (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            enrollment_id   INTEGER NOT NULL,
            employee_id     TEXT    NOT NULL,
            action          TEXT    NOT NULL,
            detail          TEXT,
            performed_by    TEXT    NOT NULL,
            performer_role  TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        CREATE TABLE IF NOT EXISTS ld_quizzes (
            id                   SERIAL  PRIMARY KEY,
            institution_id       INTEGER NOT NULL REFERENCES institutions(id),
            course_id            INTEGER NOT NULL REFERENCES ld_courses(id) UNIQUE,
            title                TEXT    NOT NULL,
            pass_threshold       INTEGER NOT NULL DEFAULT 80,
            max_attempts         INTEGER NOT NULL DEFAULT 3,
            randomize_questions  INTEGER NOT NULL DEFAULT 0,
            randomize_options    INTEGER NOT NULL DEFAULT 0,
            created_by           TEXT    NOT NULL,
            created_at           TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        CREATE TABLE IF NOT EXISTS ld_quiz_questions (
            id              SERIAL  PRIMARY KEY,
            quiz_id         INTEGER NOT NULL REFERENCES ld_quizzes(id),
            institution_id  INTEGER NOT NULL,
            question_text   TEXT    NOT NULL,
            question_type   TEXT    NOT NULL DEFAULT 'single',
            options         JSONB   NOT NULL,
            order_index     INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS ld_quiz_attempts (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            quiz_id         INTEGER NOT NULL REFERENCES ld_quizzes(id),
            enrollment_id   INTEGER NOT NULL REFERENCES ld_enrollments(id),
            employee_id     TEXT    NOT NULL,
            attempt_number  INTEGER NOT NULL DEFAULT 1,
            score           REAL    NOT NULL,
            passed          INTEGER NOT NULL DEFAULT 0,
            answers         JSONB,
            submitted_at    TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        CREATE TABLE IF NOT EXISTS ld_course_modules (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            course_id       INTEGER NOT NULL REFERENCES ld_courses(id),
            title           TEXT    NOT NULL,
            content_type    TEXT    NOT NULL DEFAULT 'text',
            content         TEXT,
            order_index     INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS ld_lesson_progress (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            enrollment_id   INTEGER NOT NULL REFERENCES ld_enrollments(id),
            module_id       INTEGER NOT NULL REFERENCES ld_course_modules(id),
            employee_id     TEXT    NOT NULL,
            viewed_at       TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(enrollment_id, module_id)
        );

        CREATE TABLE IF NOT EXISTS holidays (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            name            TEXT    NOT NULL,
            date            TEXT    NOT NULL,
            year            INTEGER NOT NULL,
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(institution_id, date)
        );

        CREATE TABLE IF NOT EXISTS leave_types (
            id                  SERIAL  PRIMARY KEY,
            institution_id      INTEGER NOT NULL REFERENCES institutions(id),
            name                TEXT    NOT NULL,
            annual_entitlement  REAL    NOT NULL DEFAULT 14,
            requires_approval   INTEGER NOT NULL DEFAULT 1,
            requires_attachment INTEGER NOT NULL DEFAULT 0,
            is_active           INTEGER NOT NULL DEFAULT 1,
            created_at          TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        CREATE TABLE IF NOT EXISTS leave_balances (
            id                      SERIAL  PRIMARY KEY,
            institution_id          INTEGER NOT NULL,
            employee_id             TEXT    NOT NULL,
            leave_type_id           INTEGER NOT NULL REFERENCES leave_types(id),
            year                    INTEGER NOT NULL,
            entitled_days           REAL    NOT NULL DEFAULT 0,
            carried_forward_days    REAL    NOT NULL DEFAULT 0,
            used_days               REAL    NOT NULL DEFAULT 0,
            UNIQUE(employee_id, leave_type_id, year)
        );

        CREATE TABLE IF NOT EXISTS leave_applications (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            employee_id     TEXT    NOT NULL,
            leave_type_id   INTEGER NOT NULL REFERENCES leave_types(id),
            start_date      TEXT    NOT NULL,
            end_date        TEXT    NOT NULL,
            days_count      REAL    NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'Pending Approval',
            reason          TEXT,
            attachment      TEXT,
            requested_by    TEXT    NOT NULL,
            approved_by     TEXT,
            notes           TEXT,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        CREATE TABLE IF NOT EXISTS leave_audit_log (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            application_id  INTEGER NOT NULL,
            employee_id     TEXT    NOT NULL,
            action          TEXT    NOT NULL,
            detail          TEXT,
            performed_by    TEXT    NOT NULL,
            performer_role  TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        CREATE TABLE IF NOT EXISTS projects (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            name            TEXT    NOT NULL,
            description     TEXT,
            status          TEXT    NOT NULL DEFAULT 'Active',
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        CREATE TABLE IF NOT EXISTS project_tasks (
            id                  SERIAL  PRIMARY KEY,
            institution_id      INTEGER NOT NULL,
            project_id          INTEGER NOT NULL REFERENCES projects(id),
            name                TEXT    NOT NULL,
            description         TEXT,
            estimated_hours     REAL,
            start_date          TEXT,
            end_date            TEXT,
            status              TEXT    NOT NULL DEFAULT 'Not Started',
            created_by          TEXT    NOT NULL,
            created_at          TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );

        CREATE TABLE IF NOT EXISTS timesheets (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            employee_id     TEXT    NOT NULL,
            period_start    TEXT    NOT NULL,
            period_end      TEXT    NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'Draft',
            submitted_at    TEXT,
            approved_by     TEXT,
            notes           TEXT,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(employee_id, period_start, period_end)
        );

        CREATE TABLE IF NOT EXISTS timesheet_entries (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            timesheet_id    INTEGER NOT NULL REFERENCES timesheets(id),
            project_id      INTEGER NOT NULL REFERENCES projects(id),
            task_id         INTEGER REFERENCES project_tasks(id),
            date            TEXT    NOT NULL,
            hours           REAL    NOT NULL,
            description     TEXT
        );

        CREATE TABLE IF NOT EXISTS timesheet_audit_log (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            timesheet_id    INTEGER NOT NULL,
            employee_id     TEXT    NOT NULL,
            action          TEXT    NOT NULL,
            detail          TEXT,
            performed_by    TEXT    NOT NULL,
            performer_role  TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        );
    """)
    conn.commit()

    # Idempotent column additions for tables that pre-date a schema change
    # (CREATE TABLE IF NOT EXISTS above is a no-op once the table already exists).
    conn.execute("ALTER TABLE ob_templates ADD COLUMN IF NOT EXISTS linked_ld_course_id INTEGER")
    conn.execute("ALTER TABLE ob_checklist_items ADD COLUMN IF NOT EXISTS linked_ld_course_id INTEGER")
    conn.execute("ALTER TABLE ob_checklist_items ADD COLUMN IF NOT EXISTS linked_ld_enrollment_id INTEGER")
    conn.execute("ALTER TABLE ld_quizzes ADD COLUMN IF NOT EXISTS randomize_questions INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE ld_quizzes ADD COLUMN IF NOT EXISTS randomize_options INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE ld_quiz_questions ADD COLUMN IF NOT EXISTS question_type TEXT NOT NULL DEFAULT 'single'")
    conn.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS logo_url TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS project_tasks (
            id                  SERIAL  PRIMARY KEY,
            institution_id      INTEGER NOT NULL,
            project_id          INTEGER NOT NULL REFERENCES projects(id),
            name                TEXT    NOT NULL,
            description         TEXT,
            estimated_hours     REAL,
            start_date          TEXT,
            end_date            TEXT,
            status              TEXT    NOT NULL DEFAULT 'Not Started',
            created_by          TEXT    NOT NULL,
            created_at          TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    conn.execute("ALTER TABLE timesheet_entries ADD COLUMN IF NOT EXISTS task_id INTEGER REFERENCES project_tasks(id)")
    conn.execute("ALTER TABLE project_tasks ADD COLUMN IF NOT EXISTS open_to_all INTEGER NOT NULL DEFAULT 0")
    # project_members retired — task-level assignments (task_assignments) plus the
    # per-task "open to all" flag now fully cover project/task access control.
    conn.execute("DROP TABLE IF EXISTS project_members")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_assignments (
            id                  SERIAL  PRIMARY KEY,
            institution_id      INTEGER NOT NULL,
            task_id             INTEGER NOT NULL REFERENCES project_tasks(id),
            employee_id         TEXT    NOT NULL,
            start_datetime      TEXT    NOT NULL,
            duration_hours      REAL    NOT NULL,
            assigned_by         TEXT    NOT NULL,
            assigned_at         TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(task_id, employee_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS institution_notifications (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            message         TEXT    NOT NULL,
            start_time      TEXT    NOT NULL,
            end_time        TEXT    NOT NULL,
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_notifications (
            id              SERIAL  PRIMARY KEY,
            message         TEXT    NOT NULL,
            start_time      TEXT    NOT NULL,
            end_time        TEXT    NOT NULL,
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS payroll_runs (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            period_start    TEXT    NOT NULL,
            period_end      TEXT    NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'Draft',
            created_by      TEXT    NOT NULL,
            finalized_by    TEXT,
            finalized_at    TEXT,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(institution_id, period_start, period_end)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS payslips (
            id                  SERIAL  PRIMARY KEY,
            institution_id      INTEGER NOT NULL,
            payroll_run_id      INTEGER NOT NULL REFERENCES payroll_runs(id),
            employee_id         TEXT    NOT NULL,
            basic_salary        NUMERIC(12,2) NOT NULL DEFAULT 0,
            unpaid_leave_days   REAL    NOT NULL DEFAULT 0,
            unpaid_leave_deduction NUMERIC(12,2) NOT NULL DEFAULT 0,
            gross_pay           NUMERIC(12,2) NOT NULL DEFAULT 0,
            epf_employee        NUMERIC(12,2) NOT NULL DEFAULT 0,
            epf_employer        NUMERIC(12,2) NOT NULL DEFAULT 0,
            socso_employee      NUMERIC(12,2) NOT NULL DEFAULT 0,
            socso_employer      NUMERIC(12,2) NOT NULL DEFAULT 0,
            eis_employee        NUMERIC(12,2) NOT NULL DEFAULT 0,
            eis_employer        NUMERIC(12,2) NOT NULL DEFAULT 0,
            pcb                 NUMERIC(12,2) NOT NULL DEFAULT 0,
            net_pay             NUMERIC(12,2) NOT NULL DEFAULT 0,
            created_at          TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(payroll_run_id, employee_id)
        )
    """)
    conn.commit()
    conn.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS pay_cycle TEXT NOT NULL DEFAULT 'Monthly'")
    conn.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS pay_day INTEGER NOT NULL DEFAULT 25")
    conn.execute("ALTER TABLE leave_types ADD COLUMN IF NOT EXISTS is_paid INTEGER NOT NULL DEFAULT 1")
    conn.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS num_children INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS salary_type TEXT NOT NULL DEFAULT 'Monthly'")
    conn.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS hourly_rate NUMERIC(12,2) NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE payslips ADD COLUMN IF NOT EXISTS salary_type TEXT NOT NULL DEFAULT 'Monthly'")
    conn.execute("ALTER TABLE payslips ADD COLUMN IF NOT EXISTS regular_hours REAL NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE payslips ADD COLUMN IF NOT EXISTS overtime_hours REAL NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE payslips ADD COLUMN IF NOT EXISTS overtime_pay NUMERIC(12,2) NOT NULL DEFAULT 0")
    conn.commit()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS performance_cycles (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            name            TEXT    NOT NULL,
            period_start    TEXT    NOT NULL,
            period_end      TEXT    NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'Draft',
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS goals (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            cycle_id        INTEGER NOT NULL REFERENCES performance_cycles(id),
            employee_id     TEXT    NOT NULL,
            goal_type       TEXT    NOT NULL DEFAULT 'KPI',
            title           TEXT    NOT NULL,
            description     TEXT,
            weight          REAL    NOT NULL DEFAULT 0,
            target_value    REAL,
            actual_value    REAL,
            unit            TEXT,
            status          TEXT    NOT NULL DEFAULT 'Draft',
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS okr_key_results (
            id              SERIAL  PRIMARY KEY,
            goal_id         INTEGER NOT NULL REFERENCES goals(id),
            description     TEXT    NOT NULL,
            target_value    REAL    NOT NULL DEFAULT 100,
            actual_value    REAL    NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS appraisals (
            id                  SERIAL  PRIMARY KEY,
            institution_id      INTEGER NOT NULL,
            cycle_id            INTEGER NOT NULL REFERENCES performance_cycles(id),
            employee_id         TEXT    NOT NULL,
            status              TEXT    NOT NULL DEFAULT 'SelfReview',
            self_rating         REAL,
            self_comments       TEXT,
            manager_rating      REAL,
            manager_comments    TEXT,
            calibrated_rating   REAL,
            calibration_notes   TEXT,
            final_rating        REAL,
            finalized_by        TEXT,
            finalized_at        TEXT,
            created_at          TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(cycle_id, employee_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS appraisal_audit_log (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            appraisal_id    INTEGER NOT NULL,
            employee_id     TEXT    NOT NULL,
            action          TEXT    NOT NULL,
            detail          TEXT,
            performed_by    TEXT    NOT NULL,
            performer_role  TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS performance_payouts (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            appraisal_id    INTEGER NOT NULL REFERENCES appraisals(id),
            employee_id     TEXT    NOT NULL,
            payout_type     TEXT    NOT NULL,
            amount          NUMERIC(12,2) NOT NULL DEFAULT 0,
            increment_pct   REAL,
            status          TEXT    NOT NULL DEFAULT 'Pending',
            payroll_run_id  INTEGER REFERENCES payroll_runs(id),
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            applied_at      TEXT
        )
    """)
    conn.commit()
    conn.execute("ALTER TABLE payslips ADD COLUMN IF NOT EXISTS bonus_amount NUMERIC(12,2) NOT NULL DEFAULT 0")
    conn.commit()

    # Currency columns migrated from REAL (float) to NUMERIC(12,2) (exact
    # fixed-point decimal) to eliminate float storage/aggregation drift —
    # rehearsed against a temp copy of payslips before running for real (see
    # tech-debt notes). CREATE TABLE / ADD COLUMN above already declare these
    # as NUMERIC for fresh installs; the ALTERs below bring an existing
    # database's already-created REAL columns in line. Safe to re-run: a
    # column already NUMERIC(12,2) is a no-op.
    for _tbl, _col in [
        ("employees", "basic_salary"), ("employees", "hourly_rate"),
        ("job_requisitions", "salary_min"), ("job_requisitions", "salary_max"),
        ("candidates", "expected_salary"),
        ("offers", "salary_offered"),
        ("ld_courses", "cost"),
        ("payslips", "basic_salary"), ("payslips", "unpaid_leave_deduction"),
        ("payslips", "gross_pay"), ("payslips", "epf_employee"), ("payslips", "epf_employer"),
        ("payslips", "socso_employee"), ("payslips", "socso_employer"),
        ("payslips", "eis_employee"), ("payslips", "eis_employer"),
        ("payslips", "pcb"), ("payslips", "net_pay"),
        ("payslips", "overtime_pay"), ("payslips", "bonus_amount"),
        ("performance_payouts", "amount"),
    ]:
        conn.execute(f"ALTER TABLE {_tbl} ALTER COLUMN {_col} TYPE NUMERIC(12,2) USING {_col}::numeric(12,2)")
    conn.commit()

    # Enable RLS on every table so Supabase's auto-exposed PostgREST/GraphQL API
    # can't read/write this data. Our app connects as the table owner (postgres),
    # which bypasses RLS by default — access control stays enforced in the API layer.
    for tbl in (
        "institutions", "users", "employees", "audit_logs", "job_requisitions",
        "candidates", "interviews", "interview_scores", "offers",
        "candidate_audit_log", "ob_audit_log", "hr_notes",
        "ob_templates", "ob_checklists", "ob_checklist_items",
        "ld_courses", "ld_enrollments", "ld_audit_log",
        "ld_quizzes", "ld_quiz_questions", "ld_quiz_attempts",
        "ld_course_modules", "ld_lesson_progress",
        "holidays", "leave_types", "leave_balances", "leave_applications", "leave_audit_log",
        "projects", "project_tasks", "timesheets", "timesheet_entries", "timesheet_audit_log",
        "task_assignments", "institution_notifications", "system_notifications",
        "payroll_runs", "payslips",
        "performance_cycles", "goals", "okr_key_results", "appraisals", "appraisal_audit_log", "performance_payouts",
    ):
        conn.execute(f"ALTER TABLE public.{tbl} ENABLE ROW LEVEL SECURITY")
    conn.commit()

    # Seed platform superadmin
    if not conn.execute("SELECT id FROM users WHERE role='superadmin' LIMIT 1").fetchone():
        conn.execute("""
            INSERT INTO users (institution_id, username, full_name, email, password_hash, role)
            VALUES (NULL, ?, ?, ?, ?, 'superadmin')
        """, ("superadmin", "Platform Administrator", "admin@platform.com", hash_password("Admin@123")))
        conn.commit()

    # Seed OB templates for existing institutions that don't have them
    inst_ids = [r[0] for r in conn.execute("SELECT id FROM institutions").fetchall()]
    for iid in inst_ids:
        seed_ob_templates(conn, iid)
    if inst_ids:
        conn.commit()

    conn.close()

init_db()

# make_token, decode_token, get_current_user, require_roles, need_inst
# imported from core.deps above.

# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------
SENSITIVE = {"bank_account", "income_tax_number", "socso_number", "epf_number"}
FIELD_LABELS = {
    "employee_id":"Employee ID",
    "full_name":"Full Name","preferred_name":"Preferred Name","ic_number":"IC Number",
    "passport_number":"Passport Number","nationality":"Nationality","race":"Race",
    "religion":"Religion","gender":"Gender","date_of_birth":"Date of Birth",
    "marital_status":"Marital Status","personal_email":"Personal Email","phone":"Phone",
    "address":"Address","department":"Department","designation":"Designation",
    "employment_type":"Employment Type","start_date":"Start Date",
    "probation_end_date":"Probation End Date","contract_end_date":"Contract End Date",
    "work_email":"Work Email","epf_number":"EPF Number","socso_number":"SOCSO Number",
    "income_tax_number":"Income Tax No.","bank_name":"Bank Name","bank_account":"Bank Account",
    "basic_salary":"Basic Salary","num_children":"No. of Children","salary_type":"Salary Type","hourly_rate":"Hourly Rate",
    "reports_to":"Reports To","status":"Status",
}

# write_audit moved to core/audit.py (imported near the top of this file)
# since routers/performance.py needs it too and routers must not import
# from main.py.

def diff_employee(old, new):
    out = []
    for f, label in FIELD_LABELS.items():
        ov, nv = str(old.get(f) or ""), str(new.get(f) or "")
        if ov != nv:
            out.append({"field":f,"label":label,
                        "old":"***" if f in SENSITIVE else ov,
                        "new":"***" if f in SENSITIVE else nv})
    return out

def write_employee_change_note(conn, inst_id, emp_id, actor, changes):
    """Mirror any employee record change into a General HR Note, so the change
    history is visible on the employee's profile, not just the Audit Log."""
    if not changes:
        return
    lines = [f'{c["label"]} changed from "{c["old"] or "—"}" to "{c["new"] or "—"}"' for c in changes]
    body = "Employee record updated — " + "; ".join(lines) + "."
    conn.execute(
        "INSERT INTO hr_notes (institution_id, employee_id, note_type, body, created_by) VALUES (?,?,?,?,?)",
        (inst_id, emp_id, "general", body, actor["username"])
    )

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
# InstitutionIn/InstitutionUpdate/InstStatusIn moved to routers/institutions.py.
# MAX_LOGO_DATA_URL_LEN / logo_url validation moved to core/validators.py
# (imported near the top of this file as _validate_logo_url) since EmployeeIn
# below still needs it.

class EmployeeIn(BaseModel):
    full_name: str
    preferred_name: Optional[str] = None
    ic_number: str
    passport_number: Optional[str] = None
    nationality: str = "Malaysian"
    race: Optional[str] = None
    religion: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    marital_status: Optional[str] = None
    personal_email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    department: str
    designation: str
    employment_type: str
    start_date: str
    probation_end_date: Optional[str] = None
    contract_end_date: Optional[str] = None
    work_email: Optional[str] = None
    epf_number: Optional[str] = None
    socso_number: Optional[str] = None
    income_tax_number: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    basic_salary: float = 0.0
    num_children: int = 0  # for PCB (income tax) child relief
    salary_type: str = "Monthly"  # Monthly | Hourly
    hourly_rate: float = 0.0  # used when salary_type == "Hourly"
    reports_to: Optional[str] = None
    employee_id: Optional[str] = None  # HR Manager only — custom/renamed Employee ID

    @field_validator("salary_type")
    @classmethod
    def validate_salary_type(cls, v):
        if v not in ("Monthly", "Hourly"):
            raise ValueError("salary_type must be Monthly or Hourly")
        return v

    @field_validator("employee_id")
    @classmethod
    def validate_employee_id(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Employee ID cannot be blank")
        return v

    @field_validator("ic_number")
    @classmethod
    def validate_ic(cls, v):
        d = v.replace("-","").replace(" ","")
        if len(d)==12 and d.isdigit():
            return f"{d[:6]}-{d[6:8]}-{d[8:]}"
        raise ValueError("IC number must be 12 digits (e.g. 900101-14-1234)")

    @field_validator("race")
    @classmethod
    def validate_race(cls, v):
        if v not in RACES: raise ValueError(f"Race must be one of: {', '.join(RACES)}")
        return v

    @field_validator("religion")
    @classmethod
    def validate_religion(cls, v):
        if v not in RELIGIONS: raise ValueError(f"Religion must be one of: {', '.join(RELIGIONS)}")
        return v

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v):
        if v not in GENDERS: raise ValueError("Gender must be Male or Female")
        return v

    @field_validator("marital_status")
    @classmethod
    def validate_marital(cls, v):
        if v not in MARITAL_STATUSES: raise ValueError(f"Marital status must be one of: {', '.join(MARITAL_STATUSES)}")
        return v

    @field_validator("employment_type")
    @classmethod
    def validate_emp_type(cls, v):
        if v not in EMPLOYMENT_TYPES: raise ValueError(f"Employment type must be one of: {', '.join(EMPLOYMENT_TYPES)}")
        return v

    @field_validator("basic_salary")
    @classmethod
    def validate_salary(cls, v):
        if v < 0: raise ValueError("Salary cannot be negative")
        return v

class BulkUploadIn(BaseModel):
    csv_content: str

class StatusUpdate(BaseModel):
    status: str
    @field_validator("status")
    @classmethod
    def val(cls, v):
        if v not in STATUSES: raise ValueError("Status must be Active or Inactive")
        return v

class LoginIn(BaseModel):
    username: str
    password: str
    institution_code: Optional[str] = None  # required for institution users, blank for superadmin

# UserIn/UserUpdate moved to routers/users.py.

class SwitchRoleIn(BaseModel):
    role: str

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

# ---------------------------------------------------------------------------
# Employee ID generator (per institution)
# ---------------------------------------------------------------------------
def gen_employee_id(conn, inst_id: int) -> str:
    cnt = conn.execute(
        "SELECT COUNT(*) FROM employees WHERE institution_id=?", (inst_id,)
    ).fetchone()[0]
    n = cnt + 1
    while True:
        eid = f"EMP{n:04d}"
        if not conn.execute(
            "SELECT id FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, eid)
        ).fetchone():
            return eid
        n += 1

# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.post("/api/auth/login")
def login(body: LoginIn, request: Request):
    rate_key = _login_rate_key(request, body.username)
    _check_login_rate_limit(rate_key)

    conn = get_db()
    code = body.institution_code.strip().upper() if body.institution_code and body.institution_code.strip() else None

    if code:
        # Institution user: look up institution first, then find user scoped to it
        inst_row = conn.execute(
            "SELECT id, name, code, status, logo_url FROM institutions WHERE code=?", (code,)
        ).fetchone()
        if not inst_row:
            conn.close()
            _record_login_failure(rate_key)
            raise HTTPException(401, "Invalid company code, username or password")
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND institution_id=?",
            (body.username, inst_row["id"])
        ).fetchone()
        inst = inst_row
    else:
        # Superadmin or platform-level login (no institution)
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND institution_id IS NULL", (body.username,)
        ).fetchone()
        inst = None

    conn.close()
    if not user or not verify_password(body.password, user["password_hash"]):
        _record_login_failure(rate_key)
        raise HTTPException(401, "Invalid company code, username or password")
    if not user["is_active"]:
        raise HTTPException(403, "Account is deactivated")
    if inst and inst["status"] != "Active":
        raise HTTPException(403, "Your company account has been suspended. Please contact platform support.")
    _clear_login_failures(rate_key)
    token = make_token(dict(user))
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "roles": [r.strip() for r in (user["roles"] or user["role"]).split(",") if r.strip()],
            "institution_id": user["institution_id"],
            "department": user["department"],
            "employee_id": user["employee_id"],
            "institution": dict(inst) if inst else None,
        }
    }

@app.post("/api/auth/switch-role")
def switch_role(body: SwitchRoleIn, user: dict = Depends(get_current_user)):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "User not found")
    allowed = [r.strip() for r in (row["roles"] or row["role"]).split(",") if r.strip()]
    if body.role not in allowed:
        conn.close()
        raise HTTPException(403, f"Role '{body.role}' is not assigned to this user")
    inst_row = conn.execute(
        "SELECT id, name, code, status, logo_url FROM institutions WHERE id=?", (row["institution_id"],)
    ).fetchone() if row["institution_id"] else None
    conn.close()
    user_dict = dict(row)
    user_dict["role"] = body.role
    token = make_token(user_dict)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": row["id"],
            "username": row["username"],
            "full_name": row["full_name"],
            "role": body.role,
            "roles": allowed,
            "institution_id": row["institution_id"],
            "department": row["department"],
            "employee_id": row["employee_id"],
            "institution": dict(inst_row) if inst_row else None,
        }
    }

@app.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)):
    return user

# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------
@app.get("/api/meta")
def get_meta(user: dict = Depends(get_current_user)):
    return {
        "races": RACES, "religions": RELIGIONS, "genders": GENDERS,
        "marital_statuses": MARITAL_STATUSES, "employment_types": EMPLOYMENT_TYPES,
        "statuses": STATUSES, "banks": BANKS, "roles": ROLES,
        "institution_roles": INSTITUTION_ROLES,
        "role_labels": ROLE_LABELS, "plans": PLANS, "plan_labels": PLAN_LABELS,
    }

# Institution CRUD routes now live in routers/institutions.py, mounted
# above via app.include_router(institutions_router).

# ---------------------------------------------------------------------------
# Employee routes (institution-scoped)
# ---------------------------------------------------------------------------
CAN_WRITE  = ("superadmin","hr_manager","hr_admin")
CAN_TOGGLE = ("superadmin","hr_manager")

# _is_self_or_subordinate / _subordinates_in_clause moved to
# core/org_queries.py (imported near the top of this file) since they're
# shared by several not-yet-extracted routers as well as routers/leave.py
# and routers/onboarding.py.
_is_self_or_subordinate = is_self_or_subordinate
_subordinates_in_clause = subordinates_in_clause

@app.get("/api/employees")
def list_employees(
    status: Optional[str] = None,
    search: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    inst_id = need_inst(user)
    conn = get_db()
    if user["role"] == "manager" and user.get("employee_id"):
        # Self + full downstream reporting chain (not just same-department peers)
        q = """
            WITH RECURSIVE subordinates AS (
                SELECT employee_id FROM employees WHERE institution_id=? AND employee_id=?
                UNION ALL
                SELECT e.employee_id FROM employees e
                JOIN subordinates s ON e.reports_to = s.employee_id
                WHERE e.institution_id=?
            )
            SELECT * FROM employees
            WHERE institution_id=? AND employee_id IN (SELECT employee_id FROM subordinates)
        """
        p = [inst_id, user["employee_id"], inst_id, inst_id]
    else:
        q = "SELECT * FROM employees WHERE institution_id=?"
        p = [inst_id]
        if user["role"] == "employee":
            q += " AND employee_id=?"; p.append(user["employee_id"])
    if status: q += " AND status=?"; p.append(status)
    if search and user["role"] != "employee":
        like = f"%{search}%"
        q += " AND (full_name LIKE ? OR employee_id LIKE ? OR ic_number LIKE ? OR designation LIKE ? OR department LIKE ?)"
        p.extend([like,like,like,like,like])
    q += " ORDER BY created_at DESC"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/employees", status_code=201)
def _insert_new_employee(conn, inst_id, emp: EmployeeIn, user: dict, ip: Optional[str]):
    """Core employee-creation logic, shared by the single Add Employee form and bulk upload.
    Raises HTTPException on business-rule violations; lets IntegrityError propagate to the caller."""
    if emp.employee_id and user["role"] == "hr_manager":
        emp_id = emp.employee_id
        if conn.execute(
            "SELECT id FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, emp_id)
        ).fetchone():
            raise HTTPException(400, f"Employee ID '{emp_id}' is already in use in this institution")
    else:
        emp_id = gen_employee_id(conn, inst_id)
    reports_to = emp_id if emp.reports_to == "SELF" else emp.reports_to
    if reports_to and reports_to != emp_id:
        if not conn.execute(
            "SELECT id FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, reports_to)
        ).fetchone():
            raise HTTPException(400, f"Reporting manager '{reports_to}' not found")
    conn.execute("""
        INSERT INTO employees (
            institution_id, employee_id, full_name, preferred_name, ic_number, passport_number,
            nationality, race, religion, gender, date_of_birth, marital_status,
            personal_email, phone, address, department, designation, employment_type, start_date,
            probation_end_date, contract_end_date, work_email,
            epf_number, socso_number, income_tax_number, bank_name, bank_account, basic_salary, num_children,
            salary_type, hourly_rate, reports_to
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (inst_id, emp_id, emp.full_name, emp.preferred_name, emp.ic_number, emp.passport_number,
          emp.nationality, emp.race or '', emp.religion or '', emp.gender or '', emp.date_of_birth or '', emp.marital_status or '',
          emp.personal_email, emp.phone, emp.address, emp.department, emp.designation,
          emp.employment_type, emp.start_date, emp.probation_end_date, emp.contract_end_date,
          emp.work_email, emp.epf_number, emp.socso_number, emp.income_tax_number,
          emp.bank_name, emp.bank_account, emp.basic_salary, emp.num_children,
          emp.salary_type, emp.hourly_rate, reports_to))
    write_audit(conn, user, inst_id, emp_id, emp.full_name, "CREATE", None, ip)
    conn.execute(
        "INSERT INTO hr_notes (institution_id, employee_id, note_type, body, created_by) VALUES (?,?,?,?,?)",
        (inst_id, emp_id, "general", "Employee record created.", user["username"])
    )
    return emp_id

def create_employee(emp: EmployeeIn, request: Request, user: dict = Depends(require_roles(*CAN_WRITE))):
    inst_id = need_inst(user)
    conn = get_db()
    # Enforce max_employees
    inst = conn.execute("SELECT max_employees FROM institutions WHERE id=?", (inst_id,)).fetchone()
    if inst:
        cnt = conn.execute("SELECT COUNT(*) FROM employees WHERE institution_id=?", (inst_id,)).fetchone()[0]
        if cnt >= inst["max_employees"]:
            conn.close()
            raise HTTPException(400, f"Employee limit ({inst['max_employees']}) reached for this institution")
    try:
        emp_id = _insert_new_employee(conn, inst_id, emp, user, request.client.host if request.client else None)
        conn.commit()
        row = conn.execute("SELECT * FROM employees WHERE institution_id=? AND employee_id=?",
                           (inst_id, emp_id)).fetchone()
        return dict(row)
    except IntegrityError as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Bulk Employee Upload (HR Manager only)
# ---------------------------------------------------------------------------
BULK_UPLOAD_ROLES = ("hr_manager",)

# Column order mirrors the single Add Employee form. Employee ID is optional —
# leave blank to auto-generate, or supply a custom one (HR Manager privilege).
BULK_UPLOAD_COLUMNS = [
    "employee_id", "full_name", "ic_number", "passport_number", "nationality",
    "race", "religion", "gender", "date_of_birth", "marital_status",
    "personal_email", "phone", "address", "department", "designation",
    "employment_type", "start_date", "probation_end_date", "contract_end_date", "work_email",
    "epf_number", "socso_number", "income_tax_number", "bank_name", "bank_account",
    "basic_salary", "num_children", "salary_type", "hourly_rate", "reports_to",
]
BULK_UPLOAD_REQUIRED = [
    "full_name", "ic_number", "race", "religion", "gender", "date_of_birth",
    "marital_status", "phone", "department", "designation", "employment_type", "start_date",
]

@app.get("/api/employees/bulk-template")
def download_bulk_template(user: dict = Depends(require_roles(*BULK_UPLOAD_ROLES))):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(BULK_UPLOAD_COLUMNS)
    example = {
        "employee_id": "", "full_name": "Jane Tan", "ic_number": "900101-14-1234", "passport_number": "",
        "nationality": "Malaysian", "race": RACES[0], "religion": RELIGIONS[0], "gender": "Female",
        "date_of_birth": "1990-01-01", "marital_status": "Single", "personal_email": "jane@example.com",
        "phone": "+60123456789", "address": "", "department": "Sales", "designation": "Sales Executive",
        "employment_type": "Permanent", "start_date": "2026-01-01", "probation_end_date": "", "contract_end_date": "",
        "work_email": "", "epf_number": "", "socso_number": "", "income_tax_number": "", "bank_name": "",
        "bank_account": "", "basic_salary": "3500", "num_children": "0", "salary_type": "Monthly",
        "hourly_rate": "0", "reports_to": "",
    }
    writer.writerow([example[c] for c in BULK_UPLOAD_COLUMNS])
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=employee-bulk-upload-template.csv"})

@app.post("/api/employees/bulk-upload")
def bulk_upload_employees(body: BulkUploadIn, request: Request, user: dict = Depends(require_roles(*BULK_UPLOAD_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    inst = conn.execute("SELECT max_employees FROM institutions WHERE id=?", (inst_id,)).fetchone()
    existing_count = conn.execute("SELECT COUNT(*) FROM employees WHERE institution_id=?", (inst_id,)).fetchone()[0]

    reader = csv.DictReader(io.StringIO(body.csv_content))
    missing_cols = [c for c in BULK_UPLOAD_REQUIRED if c not in (reader.fieldnames or [])]
    if missing_cols:
        conn.close()
        raise HTTPException(400, f"CSV is missing required column(s): {', '.join(missing_cols)}")

    created, errors = [], []
    ip = request.client.host if request.client else None
    for i, raw_row in enumerate(reader, start=2):  # row 1 is the header
        row = {k: (v.strip() if isinstance(v, str) else v) for k, v in raw_row.items()}
        if not any(row.values()):
            continue  # skip fully blank rows
        try:
            payload = {c: (row.get(c) or None) for c in BULK_UPLOAD_COLUMNS}
            if payload.get("basic_salary") in (None, ""): payload["basic_salary"] = 0
            if payload.get("num_children") in (None, ""): payload["num_children"] = 0
            if payload.get("hourly_rate") in (None, ""): payload["hourly_rate"] = 0
            if payload.get("salary_type") in (None, ""): payload["salary_type"] = "Monthly"
            if payload.get("nationality") in (None, ""): payload["nationality"] = "Malaysian"
            payload["basic_salary"] = float(payload["basic_salary"])
            payload["num_children"] = int(float(payload["num_children"]))
            payload["hourly_rate"] = float(payload["hourly_rate"])
            emp = EmployeeIn(**payload)
            if existing_count >= (inst["max_employees"] if inst else 10**9):
                errors.append({"row": i, "reason": f"Employee limit ({inst['max_employees']}) reached for this institution"})
                continue
            emp_id = _insert_new_employee(conn, inst_id, emp, user, ip)
            conn.commit()
            existing_count += 1
            created.append({"row": i, "employee_id": emp_id, "full_name": emp.full_name})
        except ValidationError as e:
            conn.rollback()
            reasons = "; ".join(f"{err['loc'][0]}: {err['msg']}" for err in e.errors())
            errors.append({"row": i, "reason": reasons})
        except (ValueError, TypeError) as e:
            conn.rollback()
            errors.append({"row": i, "reason": str(e)})
        except HTTPException as e:
            conn.rollback()
            errors.append({"row": i, "reason": e.detail})
        except IntegrityError as e:
            conn.rollback()
            errors.append({"row": i, "reason": str(e)})
    conn.close()
    return {"created": created, "errors": errors}

@app.get("/api/employees/{employee_id}")
def get_employee(employee_id: str, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    if user["role"] == "employee" and user["employee_id"] != employee_id:
        raise HTTPException(403, "Access denied")
    conn = get_db()
    if user["role"] == "manager" and not _is_self_or_subordinate(conn, inst_id, user.get("employee_id"), employee_id):
        conn.close(); raise HTTPException(403, "Access denied")
    row = conn.execute(
        "SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, employee_id)
    ).fetchone()
    conn.close()
    if not row: raise HTTPException(404, "Employee not found")
    return dict(row)

@app.put("/api/employees/{employee_id}")
def update_employee(employee_id: str, emp: EmployeeIn, request: Request,
                    user: dict = Depends(require_roles(*CAN_WRITE))):
    inst_id = need_inst(user)
    conn = get_db()
    old_row = conn.execute(
        "SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, employee_id)
    ).fetchone()
    if not old_row: conn.close(); raise HTTPException(404, "Employee not found")
    old = dict(old_row)
    try:
        new_id = employee_id
        if emp.employee_id and emp.employee_id != employee_id:
            if user["role"] != "hr_manager":
                raise HTTPException(403, "Only the HR Manager role can change Employee ID")
            new_id = emp.employee_id
            if conn.execute(
                "SELECT id FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, new_id)
            ).fetchone():
                raise HTTPException(400, f"Employee ID '{new_id}' is already in use in this institution")
            # employee_id is a soft key referenced (as plain TEXT, no DB-level FK) across many
            # tables — rename it everywhere in one transaction so nothing gets silently orphaned.
            conn.execute("UPDATE employees SET employee_id=? WHERE institution_id=? AND employee_id=?", (new_id, inst_id, employee_id))
            conn.execute("UPDATE employees SET reports_to=? WHERE institution_id=? AND reports_to=?", (new_id, inst_id, employee_id))
            conn.execute("UPDATE users SET employee_id=? WHERE institution_id=? AND employee_id=?", (new_id, inst_id, employee_id))
            conn.execute("UPDATE audit_logs SET target_employee_id=? WHERE institution_id=? AND target_employee_id=?", (new_id, inst_id, employee_id))
            for tbl in ("ob_audit_log", "hr_notes", "ob_checklists", "ld_enrollments", "ld_audit_log",
                        "ld_quiz_attempts", "ld_lesson_progress", "leave_balances", "leave_applications",
                        "leave_audit_log", "timesheets", "timesheet_audit_log", "task_assignments"):
                conn.execute(f"UPDATE {tbl} SET employee_id=? WHERE institution_id=? AND employee_id=?", (new_id, inst_id, employee_id))

        reports_to = new_id if emp.reports_to == "SELF" else emp.reports_to
        if reports_to and reports_to != new_id:
            if not conn.execute(
                "SELECT id FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, reports_to)
            ).fetchone():
                raise HTTPException(400, f"Reporting manager '{reports_to}' not found")
        conn.execute("""
            UPDATE employees SET
                full_name=?,preferred_name=?,ic_number=?,passport_number=?,
                nationality=?,race=?,religion=?,gender=?,date_of_birth=?,marital_status=?,
                personal_email=?,phone=?,address=?,department=?,designation=?,employment_type=?,
                start_date=?,probation_end_date=?,contract_end_date=?,work_email=?,
                epf_number=?,socso_number=?,income_tax_number=?,bank_name=?,bank_account=?,
                basic_salary=?,num_children=?,salary_type=?,hourly_rate=?,reports_to=?
            WHERE institution_id=? AND employee_id=?
        """, (emp.full_name, emp.preferred_name, emp.ic_number, emp.passport_number,
              emp.nationality, emp.race, emp.religion, emp.gender, emp.date_of_birth,
              emp.marital_status, emp.personal_email, emp.phone, emp.address,
              emp.department, emp.designation, emp.employment_type, emp.start_date,
              emp.probation_end_date, emp.contract_end_date, emp.work_email,
              emp.epf_number, emp.socso_number, emp.income_tax_number,
              emp.bank_name, emp.bank_account, emp.basic_salary, emp.num_children,
              emp.salary_type, emp.hourly_rate, reports_to,
              inst_id, new_id))
        new_row = conn.execute(
            "SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, new_id)
        ).fetchone()
        changes = diff_employee(old, dict(new_row))
        write_audit(conn, user, inst_id, new_id, emp.full_name, "UPDATE", changes,
                    request.client.host if request.client else None)
        write_employee_change_note(conn, inst_id, new_id, user, changes)
        conn.commit()
        return dict(new_row)
    except IntegrityError as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        conn.close()

@app.patch("/api/employees/{employee_id}/status")
def update_status(employee_id: str, body: StatusUpdate, request: Request,
                  user: dict = Depends(require_roles(*CAN_TOGGLE))):
    inst_id = need_inst(user)
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, employee_id)
    ).fetchone()
    if not row: conn.close(); raise HTTPException(404, "Employee not found")
    old = dict(row)
    conn.execute("UPDATE employees SET status=? WHERE institution_id=? AND employee_id=?",
                 (body.status, inst_id, employee_id))
    action = "ACTIVATE" if body.status == "Active" else "DEACTIVATE"
    status_change = [{"field":"status","label":"Status","old":old["status"],"new":body.status}]
    write_audit(conn, user, inst_id, employee_id, row["full_name"], action,
                status_change, request.client.host if request.client else None)
    write_employee_change_note(conn, inst_id, employee_id, user, status_change)
    conn.commit()
    result = conn.execute(
        "SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, employee_id)
    ).fetchone()
    conn.close()
    return dict(result)

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

@app.get("/api/employees/{employee_id}/related-contracts")
def get_related_contracts(employee_id: str, user: dict = Depends(get_current_user)):
    """Return all employment contracts for the same person (matched by IC number)."""
    inst_id = need_inst(user)
    conn = get_db()
    target = conn.execute(
        "SELECT ic_number FROM employees WHERE employee_id=? AND institution_id=?",
        (employee_id, inst_id)
    ).fetchone()
    if not target:
        conn.close(); raise HTTPException(404, "Employee not found")
    rows = conn.execute(
        """SELECT employee_id, full_name, employment_type, designation, department,
                  start_date, contract_end_date, status, created_at
           FROM employees
           WHERE ic_number=? AND institution_id=? AND employee_id!=?
           ORDER BY start_date DESC""",
        (target["ic_number"], inst_id, employee_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/employees/{employee_id}/rehire-prefill")
def rehire_prefill(employee_id: str, user: dict = Depends(require_roles(*CAN_WRITE))):
    """Pre-fill personal details for a rehire from an existing employee record."""
    inst_id = need_inst(user)
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM employees WHERE employee_id=? AND institution_id=?",
        (employee_id, inst_id)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Employee not found")
    r = dict(row)
    return {
        "full_name": r["full_name"], "preferred_name": r["preferred_name"],
        "ic_number": r["ic_number"], "passport_number": r["passport_number"],
        "nationality": r["nationality"], "race": r["race"], "religion": r["religion"],
        "gender": r["gender"], "date_of_birth": r["date_of_birth"],
        "marital_status": r["marital_status"], "personal_email": r["personal_email"],
        "phone": r["phone"], "address": r["address"],
        "previous_employee_id": employee_id,
    }

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
# Frontend
# ---------------------------------------------------------------------------
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_CACHE_BUST_RE = re.compile(r"\?v=[A-Za-z0-9]+")
_index_html_cache = {"version": None, "content": None}

def _static_asset_version() -> str:
    """Cache-busting token derived from every file under static/ — changes
    automatically whenever any static asset's content changes. Replaces the
    previous scheme of manually editing '?v=N' across ~19 references in
    index.html by hand on every frontend change (error-prone: miss one file
    and a stale asset gets served after deploy)."""
    h = hashlib.md5()
    for root, _, files in os.walk(STATIC_DIR):
        for name in sorted(files):
            path = os.path.join(root, name)
            h.update(path.encode())
            h.update(str(os.path.getmtime(path)).encode())
    return h.hexdigest()[:10]

@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    version = _static_asset_version()
    if _index_html_cache["version"] != version:
        with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
            raw = f.read()
        _index_html_cache["content"] = _CACHE_BUST_RE.sub(f"?v={version}", raw)
        _index_html_cache["version"] = version
    return Response(content=_index_html_cache["content"], media_type="text/html")
