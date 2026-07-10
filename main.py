import os
import io
import csv
import hashlib
import json
import logging
import random
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

import psycopg2.extras

try:
    from db import get_db, IntegrityError
except ImportError:
    from ems.db import get_db, IntegrityError

try:
    import payroll_calc
except ImportError:
    from ems import payroll_calc

try:
    from core.deps import (
        hash_password, verify_password, make_token,
        get_current_user, require_roles, need_inst,
    )
    from core.onboarding_seed import seed_ob_templates
    from core.validators import validate_logo_url as _validate_logo_url
    from core.roles import ROLES, LEAVE_MANAGE_ROLES
    from core.org_queries import subordinates_in_clause
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
except ImportError:
    from ems.core.deps import (
        hash_password, verify_password, make_token,
        get_current_user, require_roles, need_inst,
    )
    from ems.core.onboarding_seed import seed_ob_templates
    from ems.core.validators import validate_logo_url as _validate_logo_url
    from ems.core.roles import ROLES, LEAVE_MANAGE_ROLES
    from ems.core.org_queries import subordinates_in_clause
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

OB_ROLES = ["employee", "manager", "hr_admin", "hr_manager"]

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

def write_audit(conn, actor, inst_id, emp_id, emp_name, action, changes, ip=None):
    conn.execute("""
        INSERT INTO audit_logs
            (institution_id, actor_id, actor_username, actor_role,
             target_employee_id, target_employee_name, action, changes, ip_address)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (inst_id, actor["id"], actor["username"], actor["role"],
          emp_id, emp_name, action, json.dumps(changes) if changes else None, ip))

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

class OBTemplateIn(BaseModel):
    type: str = "onboarding"
    title: str
    description: Optional[str] = None
    assigned_role: str = "hr_admin"
    order_index: int = 0
    linked_ld_course_id: Optional[int] = None

class OBChecklistStartIn(BaseModel):
    employee_id: str
    type: str = "onboarding"
    notes: Optional[str] = None

class OBItemUpdateIn(BaseModel):
    status: str  # Pending | Done | N/A
    notes: Optional[str] = None

class OBItemEditIn(BaseModel):
    title: str
    description: Optional[str] = None
    assigned_role: str = "hr_admin"

class OBItemAddIn(BaseModel):
    title: str
    description: Optional[str] = None
    assigned_role: str = "hr_admin"
    linked_ld_course_id: Optional[int] = None

class LDCourseIn(BaseModel):
    title: str
    category: str = "professional_development"  # mandatory | professional_development | certification
    description: Optional[str] = None
    cost: float = 0.0
    is_active: bool = True

class LDEnrollIn(BaseModel):
    employee_id: str
    course_id: int
    notes: Optional[str] = None

class LDEnrollStatusIn(BaseModel):
    status: str  # Pending Approval | Approved | Rejected | In Progress | Completed
    notes: Optional[str] = None

class LDQuizOptionIn(BaseModel):
    text: str
    is_correct: bool = False

class LDQuizQuestionIn(BaseModel):
    question_text: str
    question_type: str = "single"  # single | multi
    options: List[LDQuizOptionIn]

class LDQuizIn(BaseModel):
    title: str
    pass_threshold: int = 80  # percent
    max_attempts: int = 3
    randomize_questions: bool = False
    randomize_options: bool = False
    questions: List[LDQuizQuestionIn]

class LDQuizAttemptIn(BaseModel):
    answers: dict  # {question_id (str): [selected_option_id (int), ...]}

class LDModuleIn(BaseModel):
    title: str
    content_type: str = "text"  # text | video
    content: Optional[str] = None  # text body, or video URL for video type

class LDModulesIn(BaseModel):
    modules: List[LDModuleIn]

# LeaveTypeIn/LeaveBalanceAdjustIn/LeaveApplicationIn/LeaveStatusIn moved to
# routers/leave.py.

# ProjectIn/ProjectTaskIn/TaskAssignmentIn/TaskOpenToAllIn moved to
# routers/projects.py.

class PayrollRunIn(BaseModel):
    period_start: str  # YYYY-MM-DD
    period_end: str

class PayslipAdjustIn(BaseModel):
    basic_salary: Optional[float] = None
    unpaid_leave_days: Optional[float] = None

class PerformanceCycleIn(BaseModel):
    name: str
    period_start: str  # YYYY-MM-DD
    period_end: str

class GoalIn(BaseModel):
    cycle_id: int
    employee_id: str
    goal_type: str = "KPI"  # KPI | OKR
    title: str
    description: Optional[str] = None
    weight: float = 0.0
    target_value: Optional[float] = None
    actual_value: Optional[float] = None
    unit: Optional[str] = None

    @field_validator("goal_type")
    @classmethod
    def validate_goal_type(cls, v):
        if v not in ("KPI", "OKR"):
            raise ValueError("goal_type must be KPI or OKR")
        return v

    @field_validator("weight")
    @classmethod
    def validate_weight(cls, v):
        if v < 0 or v > 100:
            raise ValueError("weight must be between 0 and 100")
        return v

class KeyResultIn(BaseModel):
    description: str
    target_value: float = 100.0
    actual_value: float = 0.0

class SelfReviewIn(BaseModel):
    self_comments: Optional[str] = None

class ManagerReviewIn(BaseModel):
    manager_comments: Optional[str] = None
    manager_rating: Optional[float] = None  # overrides the auto-computed weighted score if provided

class CalibrateIn(BaseModel):
    calibrated_rating: Optional[float] = None
    calibration_notes: Optional[str] = None

class GoalUpdateIn(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    weight: Optional[float] = None
    target_value: Optional[float] = None
    actual_value: Optional[float] = None
    unit: Optional[str] = None

class MeritIncrementIn(BaseModel):
    increment_pct: float

    @field_validator("increment_pct")
    @classmethod
    def _pct_range(cls, v):
        if v <= 0 or v > 100:
            raise ValueError("increment_pct must be between 0 and 100")
        return v

class BonusPayoutIn(BaseModel):
    amount: float

    @field_validator("amount")
    @classmethod
    def _amount_positive(cls, v):
        if v <= 0:
            raise ValueError("amount must be greater than 0")
        return v

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

def _is_self_or_subordinate(conn, inst_id, manager_employee_id, target_employee_id):
    """True if target is the manager themselves or anywhere in their downstream reporting chain."""
    row = conn.execute("""
        WITH RECURSIVE subordinates AS (
            SELECT employee_id FROM employees WHERE institution_id=? AND employee_id=?
            UNION ALL
            SELECT e.employee_id FROM employees e
            JOIN subordinates s ON e.reports_to = s.employee_id
            WHERE e.institution_id=?
        )
        SELECT 1 FROM subordinates WHERE employee_id=?
    """, (inst_id, manager_employee_id, inst_id, target_employee_id)).fetchone()
    return row is not None

# _subordinates_in_clause moved to core/org_queries.py (imported near the
# top of this file as subordinates_in_clause) since it's shared by several
# not-yet-extracted routers as well as routers/leave.py.
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

def _log_ob(conn, inst_id: int, cl_id: int, emp_id: str, ob_type: str,
            action: str, detail: str, user: dict):
    conn.execute(
        """INSERT INTO ob_audit_log
           (institution_id,checklist_id,employee_id,ob_type,action,detail,performed_by,performer_role)
           VALUES (?,?,?,?,?,?,?,?)""",
        (inst_id, cl_id, emp_id, ob_type, action, detail,
         user["username"], user["role"])
    )

def _log_ld(conn, inst_id: int, enr_id: int, emp_id: str,
            action: str, detail: str, user: dict):
    conn.execute(
        """INSERT INTO ld_audit_log
           (institution_id,enrollment_id,employee_id,action,detail,performed_by,performer_role)
           VALUES (?,?,?,?,?,?,?)""",
        (inst_id, enr_id, emp_id, action, detail, user["username"], user["role"])
    )

# _log_leave / _compute_leave_days / _get_or_create_leave_balance moved to
# routers/leave.py (only used by the Leave routes now mounted there).

# _log_timesheet moved to routers/timesheets.py (only used there now).

def _auto_enroll_ld_course(conn, inst_id: int, employee_id: str, course_id: int, user: dict):
    """Enroll an employee in a course as part of an onboarding checklist item. Skips the
    cost-approval gate since HR is explicitly triggering the checklist. Returns the enrollment id."""
    existing = conn.execute(
        "SELECT id FROM ld_enrollments WHERE employee_id=? AND course_id=? AND institution_id=? "
        "AND status NOT IN ('Rejected','Completed') ORDER BY created_at DESC LIMIT 1",
        (employee_id, course_id, inst_id)
    ).fetchone()
    if existing:
        return existing["id"]
    course = conn.execute("SELECT * FROM ld_courses WHERE id=? AND institution_id=?", (course_id, inst_id)).fetchone()
    if not course:
        return None
    conn.execute(
        "INSERT INTO ld_enrollments (institution_id,course_id,employee_id,status,requested_by,notes) VALUES (?,?,?,?,?,?)",
        (inst_id, course_id, employee_id, "In Progress", user["username"], "Auto-enrolled via onboarding checklist")
    )
    enr_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    _log_ld(conn, inst_id, enr_id, employee_id, "Enrolled",
            f"Auto-enrolled in '{course['title']}' via onboarding checklist", user)
    return enr_id

def _complete_linked_ob_items(conn, inst_id: int, employee_id: str, course_id: int, user: dict):
    """When an L&D enrollment for this employee+course completes, auto-mark any onboarding
    checklist items linked to that course as Done, and close out the checklist if that
    was the last pending item."""
    items = conn.execute(
        """SELECT i.*, c.type AS ob_type FROM ob_checklist_items i
           JOIN ob_checklists c ON c.id = i.checklist_id
           WHERE i.linked_ld_course_id=? AND i.institution_id=? AND i.status='Pending'
             AND c.employee_id=? AND c.status='In Progress'""",
        (course_id, inst_id, employee_id)
    ).fetchall()
    for item in items:
        conn.execute(
            "UPDATE ob_checklist_items SET status='Done',completed_by=?,"
            "completed_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS'),notes=? WHERE id=?",
            (user["username"], "Auto-completed: linked course finished", item["id"])
        )
        cl_id = item["checklist_id"]
        _log_ob(conn, inst_id, cl_id, employee_id, item["ob_type"],
                "Item Auto-Completed",
                f"'{item['title']}' auto-completed after finishing the linked course", user)
        total = conn.execute("SELECT COUNT(*) FROM ob_checklist_items WHERE checklist_id=?", (cl_id,)).fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM ob_checklist_items WHERE checklist_id=? AND status IN ('Done','N/A')", (cl_id,)).fetchone()[0]
        if total > 0 and done == total:
            conn.execute(
                "UPDATE ob_checklists SET status='Completed',completed_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=?",
                (cl_id,)
            )
            _log_ob(conn, inst_id, cl_id, employee_id, item["ob_type"],
                    "Checklist Completed",
                    f"All {total} items completed — checklist auto-closed", user)

# _get_candidate / _get_req / _gen_offer_letter and all Recruitment routes
# now live in routers/recruitment.py.

# ---------------------------------------------------------------------------
# Onboarding / Offboarding — Templates
# ---------------------------------------------------------------------------
OB_MANAGE_ROLES = ("superadmin","hr_manager","hr_admin")

@app.get("/api/ob/templates")
def list_ob_templates(type: Optional[str] = None, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    q = "SELECT * FROM ob_templates WHERE institution_id=? AND is_active=1"
    p = [inst_id]
    if type:
        q += " AND type=?"; p.append(type)
    q += " ORDER BY type, order_index"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/ob/templates", status_code=201)
def create_ob_template(body: OBTemplateIn, user: dict = Depends(require_roles(*OB_MANAGE_ROLES))):
    inst_id = need_inst(user)
    if body.type not in ("onboarding","offboarding"):
        raise HTTPException(400, "type must be onboarding or offboarding")
    if body.assigned_role not in OB_ROLES:
        raise HTTPException(400, f"assigned_role must be one of: {', '.join(OB_ROLES)}")
    conn = get_db()
    conn.execute(
        "INSERT INTO ob_templates (institution_id,type,title,description,assigned_role,order_index,linked_ld_course_id) VALUES (?,?,?,?,?,?,?)",
        (inst_id, body.type, body.title, body.description, body.assigned_role, body.order_index, body.linked_ld_course_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM ob_templates WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)

@app.put("/api/ob/templates/{tmpl_id}")
def update_ob_template(tmpl_id: int, body: OBTemplateIn, user: dict = Depends(require_roles(*OB_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute("SELECT id FROM ob_templates WHERE id=? AND institution_id=?", (tmpl_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Template not found")
    conn.execute(
        "UPDATE ob_templates SET title=?,description=?,assigned_role=?,order_index=?,linked_ld_course_id=? WHERE id=?",
        (body.title, body.description, body.assigned_role, body.order_index, body.linked_ld_course_id, tmpl_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM ob_templates WHERE id=?", (tmpl_id,)).fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/ob/templates/{tmpl_id}", status_code=204)
def delete_ob_template(tmpl_id: int, user: dict = Depends(require_roles(*OB_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    conn.execute("UPDATE ob_templates SET is_active=0 WHERE id=? AND institution_id=?", (tmpl_id, inst_id))
    conn.commit(); conn.close()

# ---------------------------------------------------------------------------
# Onboarding / Offboarding — Checklists
# ---------------------------------------------------------------------------
@app.get("/api/ob/checklists")
def list_ob_checklists(type: Optional[str] = None, status: Optional[str] = None,
                       user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    q = """
        SELECT c.*, e.full_name AS employee_name, e.department, e.designation,
               COUNT(i.id) AS total_items,
               SUM(CASE WHEN i.status='Done' THEN 1 ELSE 0 END) AS done_items,
               SUM(CASE WHEN i.status='Pending' AND i.assigned_role=? THEN 1 ELSE 0 END) AS my_pending
        FROM ob_checklists c
        JOIN employees e ON e.employee_id=c.employee_id AND e.institution_id=c.institution_id
        LEFT JOIN ob_checklist_items i ON i.checklist_id=c.id
        WHERE c.institution_id=?
    """
    p: list = [user["role"], inst_id]
    if type: q += " AND c.type=?"; p.append(type)
    if status: q += " AND c.status=?"; p.append(status)
    if user["role"] == "manager":
        frag, fp = _subordinates_in_clause(inst_id, user.get("employee_id", ""))
        q += f" AND e.employee_id IN {frag}"; p.extend(fp)
    elif user["role"] == "employee":
        q += " AND c.employee_id=?"; p.append(user.get("employee_id",""))
    q += " GROUP BY c.id, e.full_name, e.department, e.designation ORDER BY c.created_at DESC"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/ob/checklists", status_code=201)
def start_ob_checklist(body: OBChecklistStartIn, user: dict = Depends(require_roles(*OB_MANAGE_ROLES))):
    inst_id = need_inst(user)
    if body.type not in ("onboarding","offboarding"):
        raise HTTPException(400, "type must be onboarding or offboarding")
    conn = get_db()
    # Check employee exists
    emp = conn.execute("SELECT * FROM employees WHERE employee_id=? AND institution_id=?",
                       (body.employee_id, inst_id)).fetchone()
    if not emp:
        conn.close(); raise HTTPException(404, "Employee not found")
    # Check not already active
    existing = conn.execute(
        "SELECT id FROM ob_checklists WHERE employee_id=? AND institution_id=? AND type=? AND status='In Progress'",
        (body.employee_id, inst_id, body.type)
    ).fetchone()
    if existing:
        conn.close(); raise HTTPException(400, f"An active {body.type} checklist already exists for this employee")
    conn.execute(
        "INSERT INTO ob_checklists (institution_id,employee_id,type,triggered_by,notes) VALUES (?,?,?,?,?)",
        (inst_id, body.employee_id, body.type, user["username"], body.notes)
    )
    cl_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Snapshot active templates as items
    templates = conn.execute(
        "SELECT * FROM ob_templates WHERE institution_id=? AND type=? AND is_active=1 ORDER BY order_index",
        (inst_id, body.type)
    ).fetchall()
    for t in templates:
        enrollment_id = None
        if t["linked_ld_course_id"]:
            enrollment_id = _auto_enroll_ld_course(conn, inst_id, body.employee_id, t["linked_ld_course_id"], user)
        conn.execute(
            "INSERT INTO ob_checklist_items (checklist_id,institution_id,template_id,title,description,assigned_role,order_index,linked_ld_course_id,linked_ld_enrollment_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (cl_id, inst_id, t["id"], t["title"], t["description"], t["assigned_role"], t["order_index"],
             t["linked_ld_course_id"], enrollment_id)
        )
    _log_ob(conn, inst_id, cl_id, body.employee_id, body.type,
            "Checklist Started",
            f"{body.type.capitalize()} checklist started for {emp['full_name']} with {len(templates)} items",
            user)
    conn.commit()
    row = conn.execute("SELECT * FROM ob_checklists WHERE id=?", (cl_id,)).fetchone()
    conn.close()
    return dict(row)

@app.get("/api/ob/checklists/{cl_id}")
def get_ob_checklist(cl_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    cl = conn.execute(
        "SELECT c.*, e.full_name AS employee_name, e.department, e.designation FROM ob_checklists c JOIN employees e ON e.employee_id=c.employee_id AND e.institution_id=c.institution_id WHERE c.id=? AND c.institution_id=?",
        (cl_id, inst_id)
    ).fetchone()
    if not cl:
        conn.close(); raise HTTPException(404, "Checklist not found")
    if user["role"] == "employee" and cl["employee_id"] != user.get("employee_id"):
        conn.close(); raise HTTPException(403, "Access denied to this checklist")
    if user["role"] == "manager" and not _is_self_or_subordinate(conn, inst_id, user.get("employee_id"), cl["employee_id"]):
        conn.close(); raise HTTPException(403, "Access denied to this checklist")
    items = conn.execute(
        "SELECT * FROM ob_checklist_items WHERE checklist_id=? ORDER BY order_index",
        (cl_id,)
    ).fetchall()
    conn.close()
    result = dict(cl)
    # Employees only see items assigned to their own role — hide other roles' tasks/notes
    if user["role"] == "employee":
        items = [i for i in items if i["assigned_role"] == "employee"]
    result["items"] = [dict(i) for i in items]
    return result

@app.patch("/api/ob/checklists/{cl_id}/items/{item_id}")
def update_ob_item(cl_id: int, item_id: int, body: OBItemUpdateIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    if body.status not in ("Pending","Done","N/A"):
        raise HTTPException(400, "status must be Pending, Done or N/A")
    conn = get_db()
    cl = conn.execute("SELECT * FROM ob_checklists WHERE id=? AND institution_id=?", (cl_id, inst_id)).fetchone()
    if not cl:
        conn.close(); raise HTTPException(404, "Checklist not found")
    item = conn.execute("SELECT * FROM ob_checklist_items WHERE id=? AND checklist_id=?", (item_id, cl_id)).fetchone()
    if not item:
        conn.close(); raise HTTPException(404, "Item not found")
    # Permission: assigned_role must match user role, or HR manager/admin can override
    can_act = (item["assigned_role"] == user["role"] or user["role"] in ("superadmin","hr_manager","hr_admin"))
    if not can_act:
        conn.close(); raise HTTPException(403, f"This item is assigned to {item['assigned_role']}")
    completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if body.status in ("Done","N/A") else None
    completed_by = user["username"] if body.status in ("Done","N/A") else None
    conn.execute(
        "UPDATE ob_checklist_items SET status=?,notes=?,completed_by=?,completed_at=? WHERE id=?",
        (body.status, body.notes, completed_by, completed_at, item_id)
    )
    # Auto-complete checklist if all items done/na
    total = conn.execute("SELECT COUNT(*) FROM ob_checklist_items WHERE checklist_id=?", (cl_id,)).fetchone()[0]
    done  = conn.execute("SELECT COUNT(*) FROM ob_checklist_items WHERE checklist_id=? AND status IN ('Done','N/A')", (cl_id,)).fetchone()[0]
    auto_completed = False
    if total > 0 and done == total:
        conn.execute("UPDATE ob_checklists SET status='Completed',completed_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=?", (cl_id,))
        auto_completed = True
    prev_status = item["status"]
    _log_ob(conn, inst_id, cl_id, cl["employee_id"], cl["type"],
            "Item Updated",
            f"'{item['title']}' changed from {prev_status} → {body.status}" +
            (f" (note: {body.notes})" if body.notes else ""),
            user)
    if auto_completed:
        _log_ob(conn, inst_id, cl_id, cl["employee_id"], cl["type"],
                "Checklist Completed",
                f"All {total} items completed — checklist auto-closed",
                user)
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/api/ob/checklists/{cl_id}", status_code=204)
def delete_ob_checklist(cl_id: int, user: dict = Depends(require_roles(*OB_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    cl = conn.execute("SELECT * FROM ob_checklists WHERE id=? AND institution_id=?", (cl_id, inst_id)).fetchone()
    if cl:
        _log_ob(conn, inst_id, cl_id, cl["employee_id"], cl["type"],
                "Checklist Deleted", "Checklist and all items removed", user)
        conn.commit()
    conn.execute("DELETE FROM ob_checklist_items WHERE checklist_id=?", (cl_id,))
    conn.execute("DELETE FROM ob_checklists WHERE id=? AND institution_id=?", (cl_id, inst_id))
    conn.commit(); conn.close()

@app.put("/api/ob/checklists/{cl_id}/items/{item_id}")
def edit_ob_item(cl_id: int, item_id: int, body: OBItemEditIn,
                 user: dict = Depends(require_roles(*OB_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute("SELECT id FROM ob_checklists WHERE id=? AND institution_id=?", (cl_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Checklist not found")
    if not conn.execute("SELECT id FROM ob_checklist_items WHERE id=? AND checklist_id=?", (item_id, cl_id)).fetchone():
        conn.close(); raise HTTPException(404, "Item not found")
    if body.assigned_role not in OB_ROLES:
        conn.close(); raise HTTPException(400, f"assigned_role must be one of: {', '.join(OB_ROLES)}")
    old = conn.execute("SELECT * FROM ob_checklist_items WHERE id=? AND checklist_id=?", (item_id, cl_id)).fetchone()
    cl2 = conn.execute("SELECT * FROM ob_checklists WHERE id=?", (cl_id,)).fetchone()
    conn.execute(
        "UPDATE ob_checklist_items SET title=?,description=?,assigned_role=? WHERE id=?",
        (body.title, body.description, body.assigned_role, item_id)
    )
    if cl2:
        _log_ob(conn, inst_id, cl_id, cl2["employee_id"], cl2["type"],
                "Item Edited",
                f"'{old['title'] if old else item_id}' → title='{body.title}', role={body.assigned_role}",
                user)
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/ob/checklists/{cl_id}/items", status_code=201)
def add_ob_item(cl_id: int, body: OBItemAddIn,
                user: dict = Depends(require_roles(*OB_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    cl = conn.execute("SELECT * FROM ob_checklists WHERE id=? AND institution_id=?", (cl_id, inst_id)).fetchone()
    if not cl:
        conn.close(); raise HTTPException(404, "Checklist not found")
    if body.assigned_role not in OB_ROLES:
        conn.close(); raise HTTPException(400, f"assigned_role must be one of: {', '.join(OB_ROLES)}")
    max_order = conn.execute("SELECT MAX(order_index) FROM ob_checklist_items WHERE checklist_id=?", (cl_id,)).fetchone()[0] or 0
    enrollment_id = None
    if body.linked_ld_course_id:
        enrollment_id = _auto_enroll_ld_course(conn, inst_id, cl["employee_id"], body.linked_ld_course_id, user)
    conn.execute(
        "INSERT INTO ob_checklist_items (checklist_id,institution_id,title,description,assigned_role,order_index,linked_ld_course_id,linked_ld_enrollment_id) VALUES (?,?,?,?,?,?,?,?)",
        (cl_id, inst_id, body.title, body.description, body.assigned_role, max_order + 1,
         body.linked_ld_course_id, enrollment_id)
    )
    _log_ob(conn, inst_id, cl_id, cl["employee_id"], cl["type"],
            "Item Added", f"New item '{body.title}' assigned to {body.assigned_role}", user)
    conn.commit()
    row = conn.execute("SELECT * FROM ob_checklist_items WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/ob/checklists/{cl_id}/items/{item_id}", status_code=204)
def delete_ob_item(cl_id: int, item_id: int,
                   user: dict = Depends(require_roles(*OB_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    cl = conn.execute("SELECT * FROM ob_checklists WHERE id=? AND institution_id=?", (cl_id, inst_id)).fetchone()
    item = conn.execute("SELECT * FROM ob_checklist_items WHERE id=? AND checklist_id=?", (item_id, cl_id)).fetchone()
    if not cl:
        conn.close(); raise HTTPException(404, "Checklist not found")
    if item and cl:
        _log_ob(conn, inst_id, cl_id, cl["employee_id"], cl["type"],
                "Item Removed", f"Item '{item['title']}' removed from checklist", user)
        conn.commit()
    conn.execute("DELETE FROM ob_checklist_items WHERE id=? AND checklist_id=?", (item_id, cl_id))
    conn.commit(); conn.close()

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

@app.get("/api/employees/{employee_id}/ob-history")
def get_employee_ob_history(employee_id: str, user: dict = Depends(require_roles(*OB_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM ob_audit_log WHERE employee_id=? AND institution_id=? ORDER BY created_at ASC",
        (employee_id, inst_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ---------------------------------------------------------------------------
# Learning & Development — Courses
# ---------------------------------------------------------------------------
LD_MANAGE_ROLES = ("superadmin", "hr_manager", "hr_admin")
LD_CATEGORIES = ("mandatory", "professional_development", "certification")

@app.get("/api/ld/courses")
def list_ld_courses(category: Optional[str] = None, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    q = "SELECT * FROM ld_courses WHERE institution_id=? AND is_active=1"
    p = [inst_id]
    if category:
        q += " AND category=?"; p.append(category)
    q += " ORDER BY category, title"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/ld/courses", status_code=201)
def create_ld_course(body: LDCourseIn, user: dict = Depends(require_roles(*LD_MANAGE_ROLES))):
    inst_id = need_inst(user)
    if body.category not in LD_CATEGORIES:
        raise HTTPException(400, f"category must be one of: {', '.join(LD_CATEGORIES)}")
    conn = get_db()
    conn.execute(
        "INSERT INTO ld_courses (institution_id,title,category,description,cost,is_active,created_by) VALUES (?,?,?,?,?,?,?)",
        (inst_id, body.title, body.category, body.description, body.cost, 1 if body.is_active else 0, user["username"])
    )
    conn.commit()
    row = conn.execute("SELECT * FROM ld_courses WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)

@app.put("/api/ld/courses/{course_id}")
def update_ld_course(course_id: int, body: LDCourseIn, user: dict = Depends(require_roles(*LD_MANAGE_ROLES))):
    inst_id = need_inst(user)
    if body.category not in LD_CATEGORIES:
        raise HTTPException(400, f"category must be one of: {', '.join(LD_CATEGORIES)}")
    conn = get_db()
    if not conn.execute("SELECT id FROM ld_courses WHERE id=? AND institution_id=?", (course_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Course not found")
    conn.execute(
        "UPDATE ld_courses SET title=?,category=?,description=?,cost=?,is_active=? WHERE id=?",
        (body.title, body.category, body.description, body.cost, 1 if body.is_active else 0, course_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM ld_courses WHERE id=?", (course_id,)).fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/ld/courses/{course_id}", status_code=204)
def delete_ld_course(course_id: int, user: dict = Depends(require_roles(*LD_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    conn.execute("UPDATE ld_courses SET is_active=0 WHERE id=? AND institution_id=?", (course_id, inst_id))
    conn.commit(); conn.close()

# ---------------------------------------------------------------------------
# Learning & Development — Enrollments
# ---------------------------------------------------------------------------
@app.get("/api/ld/enrollments")
def list_ld_enrollments(status: Optional[str] = None, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    q = """
        SELECT en.*, c.title AS course_title, c.category AS course_category, c.cost AS course_cost,
               e.full_name AS employee_name, e.department, e.designation,
               qz.id AS quiz_id,
               (SELECT COUNT(*) FROM ld_course_modules m WHERE m.course_id = c.id) AS module_count,
               (SELECT COUNT(*) FROM ld_lesson_progress lp WHERE lp.enrollment_id = en.id) AS modules_viewed
        FROM ld_enrollments en
        JOIN ld_courses c ON c.id = en.course_id
        JOIN employees e ON e.employee_id = en.employee_id AND e.institution_id = en.institution_id
        LEFT JOIN ld_quizzes qz ON qz.course_id = c.id
        WHERE en.institution_id=?
    """
    p: list = [inst_id]
    if status: q += " AND en.status=?"; p.append(status)
    if user["role"] == "manager":
        frag, fp = _subordinates_in_clause(inst_id, user.get("employee_id", ""))
        q += f" AND e.employee_id IN {frag}"; p.extend(fp)
    elif user["role"] == "employee":
        q += " AND en.employee_id=?"; p.append(user.get("employee_id", ""))
    q += " ORDER BY en.created_at DESC"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/ld/enrollments", status_code=201)
def create_ld_enrollment(body: LDEnrollIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    if user["role"] == "employee" and user.get("employee_id") != body.employee_id:
        conn.close(); raise HTTPException(403, "You can only enroll yourself")
    emp = conn.execute("SELECT * FROM employees WHERE employee_id=? AND institution_id=?",
                        (body.employee_id, inst_id)).fetchone()
    if not emp:
        conn.close(); raise HTTPException(404, "Employee not found")
    course = conn.execute("SELECT * FROM ld_courses WHERE id=? AND institution_id=? AND is_active=1",
                           (body.course_id, inst_id)).fetchone()
    if not course:
        conn.close(); raise HTTPException(404, "Course not found")
    existing = conn.execute(
        "SELECT id FROM ld_enrollments WHERE employee_id=? AND course_id=? AND status NOT IN ('Rejected','Completed')",
        (body.employee_id, body.course_id)
    ).fetchone()
    if existing:
        conn.close(); raise HTTPException(400, "Employee already has an active enrollment for this course")
    status = "Pending Approval" if course["cost"] and course["cost"] > 0 else "In Progress"
    conn.execute(
        "INSERT INTO ld_enrollments (institution_id,course_id,employee_id,status,requested_by,notes) VALUES (?,?,?,?,?,?)",
        (inst_id, body.course_id, body.employee_id, status, user["username"], body.notes)
    )
    enr_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    _log_ld(conn, inst_id, enr_id, body.employee_id, "Enrolled",
            f"Enrolled in '{course['title']}' — status: {status}", user)
    conn.commit()
    row = conn.execute("SELECT * FROM ld_enrollments WHERE id=?", (enr_id,)).fetchone()
    conn.close()
    return dict(row)

@app.patch("/api/ld/enrollments/{enr_id}/status")
def update_ld_enrollment_status(enr_id: int, body: LDEnrollStatusIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    valid_statuses = ("Pending Approval", "Approved", "Rejected", "In Progress", "Completed")
    if body.status not in valid_statuses:
        raise HTTPException(400, f"status must be one of: {', '.join(valid_statuses)}")
    conn = get_db()
    enr = conn.execute("SELECT * FROM ld_enrollments WHERE id=? AND institution_id=?", (enr_id, inst_id)).fetchone()
    if not enr:
        conn.close(); raise HTTPException(404, "Enrollment not found")

    if body.status in ("Approved", "Rejected"):
        can_approve = user["role"] in ("superadmin", "hr_manager", "hr_admin", "manager")
        if not can_approve:
            conn.close(); raise HTTPException(403, "Only a manager or HR can approve/reject enrollments")
        next_status = "In Progress" if body.status == "Approved" else "Rejected"
        conn.execute(
            "UPDATE ld_enrollments SET status=?,approved_by=?,notes=? WHERE id=?",
            (next_status, user["username"], body.notes, enr_id)
        )
        _log_ld(conn, inst_id, enr_id, enr["employee_id"], f"Enrollment {body.status}",
                f"{body.notes or ''}".strip() or f"Enrollment {body.status.lower()} by {user['username']}", user)
    elif body.status == "Completed":
        if user["role"] == "employee" and user.get("employee_id") != enr["employee_id"]:
            conn.close(); raise HTTPException(403, "Access denied")
        conn.execute(
            "UPDATE ld_enrollments SET status='Completed', completed_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=?",
            (enr_id,)
        )
        _log_ld(conn, inst_id, enr_id, enr["employee_id"], "Completed",
                f"Marked complete by {user['username']}", user)
        _complete_linked_ob_items(conn, inst_id, enr["employee_id"], enr["course_id"], user)
    else:
        conn.execute("UPDATE ld_enrollments SET status=? WHERE id=?", (body.status, enr_id))
        _log_ld(conn, inst_id, enr_id, enr["employee_id"], "Status Updated",
                f"Status changed to {body.status}", user)

    conn.commit()
    row = conn.execute("SELECT * FROM ld_enrollments WHERE id=?", (enr_id,)).fetchone()
    conn.close()
    return dict(row)

@app.get("/api/employees/{employee_id}/ld-history")
def get_employee_ld_history(employee_id: str, user: dict = Depends(require_roles(*LD_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM ld_audit_log WHERE employee_id=? AND institution_id=? ORDER BY created_at ASC",
        (employee_id, inst_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ---------------------------------------------------------------------------
# Learning & Development — Quizzes
# ---------------------------------------------------------------------------
def _quiz_for_course(conn, inst_id: int, course_id: int):
    quiz = conn.execute(
        "SELECT * FROM ld_quizzes WHERE course_id=? AND institution_id=?", (course_id, inst_id)
    ).fetchone()
    if not quiz:
        return None
    questions = conn.execute(
        "SELECT * FROM ld_quiz_questions WHERE quiz_id=? ORDER BY order_index", (quiz["id"],)
    ).fetchall()
    result = dict(quiz)
    result["questions"] = [dict(q) for q in questions]
    return result

@app.get("/api/ld/courses/{course_id}/quiz")
def get_course_quiz(course_id: int, user: dict = Depends(get_current_user)):
    """Returns the quiz for taking. Strips is_correct so answers never reach the client.
    Each option keeps a stable 'id' (its original save-time position) so that shuffled
    display order never breaks grading, which looks answers up by id, not position."""
    inst_id = need_inst(user)
    conn = get_db()
    quiz = _quiz_for_course(conn, inst_id, course_id)
    conn.close()
    if not quiz:
        raise HTTPException(404, "No quiz for this course")
    if quiz["randomize_questions"]:
        random.shuffle(quiz["questions"])
    for q in quiz["questions"]:
        opts = [{"id": o["id"], "text": o["text"]} for o in q["options"]]
        if quiz["randomize_options"]:
            random.shuffle(opts)
        q["options"] = opts
    return quiz

@app.get("/api/ld/courses/{course_id}/quiz/manage")
def get_course_quiz_for_manage(course_id: int, user: dict = Depends(require_roles(*LD_MANAGE_ROLES))):
    """Returns the quiz with correct answers included, for HR to edit."""
    inst_id = need_inst(user)
    conn = get_db()
    quiz = _quiz_for_course(conn, inst_id, course_id)
    conn.close()
    if not quiz:
        raise HTTPException(404, "No quiz for this course")
    return quiz

@app.put("/api/ld/courses/{course_id}/quiz")
def upsert_course_quiz(course_id: int, body: LDQuizIn, user: dict = Depends(require_roles(*LD_MANAGE_ROLES))):
    inst_id = need_inst(user)
    if not body.questions:
        raise HTTPException(400, "A quiz needs at least one question")
    for q in body.questions:
        if q.question_type not in ("single", "multi"):
            raise HTTPException(400, f"question_type must be 'single' or 'multi' for '{q.question_text}'")
        correct_count = sum(1 for o in q.options if o.is_correct)
        if correct_count == 0:
            raise HTTPException(400, f"Question '{q.question_text}' has no correct answer marked")
        if q.question_type == "single" and correct_count > 1:
            raise HTTPException(400, f"Question '{q.question_text}' is single-answer but has {correct_count} correct options marked")
    conn = get_db()
    course = conn.execute("SELECT id FROM ld_courses WHERE id=? AND institution_id=?", (course_id, inst_id)).fetchone()
    if not course:
        conn.close(); raise HTTPException(404, "Course not found")

    existing = conn.execute("SELECT id FROM ld_quizzes WHERE course_id=? AND institution_id=?", (course_id, inst_id)).fetchone()
    if existing:
        quiz_id = existing["id"]
        conn.execute("UPDATE ld_quizzes SET title=?,pass_threshold=?,max_attempts=?,randomize_questions=?,randomize_options=? WHERE id=?",
                     (body.title, body.pass_threshold, body.max_attempts,
                      1 if body.randomize_questions else 0, 1 if body.randomize_options else 0, quiz_id))
        conn.execute("DELETE FROM ld_quiz_questions WHERE quiz_id=?", (quiz_id,))
    else:
        conn.execute(
            "INSERT INTO ld_quizzes (institution_id,course_id,title,pass_threshold,max_attempts,randomize_questions,randomize_options,created_by) VALUES (?,?,?,?,?,?,?,?)",
            (inst_id, course_id, body.title, body.pass_threshold, body.max_attempts,
             1 if body.randomize_questions else 0, 1 if body.randomize_options else 0, user["username"])
        )
        quiz_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    for idx, q in enumerate(body.questions):
        # Each option gets a stable id (its save-time position) so shuffled display
        # order in the take-view never breaks answer grading.
        options_json = [{"id": i, "text": o.text, "is_correct": o.is_correct} for i, o in enumerate(q.options)]
        conn.execute(
            "INSERT INTO ld_quiz_questions (quiz_id,institution_id,question_text,question_type,options,order_index) VALUES (?,?,?,?,?,?)",
            (quiz_id, inst_id, q.question_text, q.question_type, psycopg2.extras.Json(options_json), idx)
        )
    conn.commit()
    quiz = _quiz_for_course(conn, inst_id, course_id)
    conn.close()
    return quiz

@app.delete("/api/ld/courses/{course_id}/quiz", status_code=204)
def delete_course_quiz(course_id: int, user: dict = Depends(require_roles(*LD_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    quiz = conn.execute("SELECT id FROM ld_quizzes WHERE course_id=? AND institution_id=?", (course_id, inst_id)).fetchone()
    if quiz:
        conn.execute("DELETE FROM ld_quiz_questions WHERE quiz_id=?", (quiz["id"],))
        conn.execute("DELETE FROM ld_quizzes WHERE id=?", (quiz["id"],))
        conn.commit()
    conn.close()

@app.post("/api/ld/quizzes/{quiz_id}/attempts", status_code=201)
def submit_quiz_attempt(quiz_id: int, body: LDQuizAttemptIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    quiz = conn.execute("SELECT * FROM ld_quizzes WHERE id=? AND institution_id=?", (quiz_id, inst_id)).fetchone()
    if not quiz:
        conn.close(); raise HTTPException(404, "Quiz not found")

    if user["role"] != "employee" or not user.get("employee_id"):
        conn.close(); raise HTTPException(403, "Only the enrolled employee can attempt this quiz")

    enrollment = conn.execute(
        "SELECT * FROM ld_enrollments WHERE course_id=? AND institution_id=? AND status='In Progress' "
        "AND employee_id=? ORDER BY created_at DESC LIMIT 1",
        (quiz["course_id"], inst_id, user["employee_id"])
    ).fetchone()
    if not enrollment:
        conn.close(); raise HTTPException(403, "You don't have an active enrollment for this course")

    prior_attempts = conn.execute(
        "SELECT COUNT(*) FROM ld_quiz_attempts WHERE quiz_id=? AND enrollment_id=?", (quiz_id, enrollment["id"])
    ).fetchone()[0]
    if prior_attempts >= quiz["max_attempts"]:
        conn.close(); raise HTTPException(400, f"Maximum attempts ({quiz['max_attempts']}) reached for this quiz")

    questions = conn.execute("SELECT * FROM ld_quiz_questions WHERE quiz_id=?", (quiz_id,)).fetchall()
    total = len(questions)
    correct = 0
    for q in questions:
        submitted = body.answers.get(str(q["id"]), [])
        if not isinstance(submitted, list):
            submitted = [submitted]  # tolerate a lone int for single-answer questions
        submitted_ids = {int(x) for x in submitted}
        correct_ids = {o["id"] for o in q["options"] if o.get("is_correct")}
        # Select-all-that-apply grading: exact match required, no partial credit —
        # picking every option would otherwise trivially "pass" multi-select questions.
        if submitted_ids == correct_ids:
            correct += 1
    score = round((correct / total) * 100, 1) if total else 0
    passed = score >= quiz["pass_threshold"]

    conn.execute(
        "INSERT INTO ld_quiz_attempts (institution_id,quiz_id,enrollment_id,employee_id,attempt_number,score,passed,answers) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (inst_id, quiz_id, enrollment["id"], enrollment["employee_id"], prior_attempts + 1,
         score, 1 if passed else 0, psycopg2.extras.Json(body.answers))
    )
    if passed:
        conn.execute(
            "UPDATE ld_enrollments SET status='Completed', completed_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=?",
            (enrollment["id"],)
        )
        _log_ld(conn, inst_id, enrollment["id"], enrollment["employee_id"], "Quiz Passed",
                f"Scored {score}% on '{quiz['title']}' (attempt {prior_attempts+1}) — course completed", user)
        _complete_linked_ob_items(conn, inst_id, enrollment["employee_id"], quiz["course_id"], user)
    else:
        _log_ld(conn, inst_id, enrollment["id"], enrollment["employee_id"], "Quiz Attempt Failed",
                f"Scored {score}% on '{quiz['title']}' (attempt {prior_attempts+1}, needed {quiz['pass_threshold']}%)", user)
    conn.commit()
    conn.close()
    return {"score": score, "passed": passed, "attempt_number": prior_attempts + 1, "max_attempts": quiz["max_attempts"]}

@app.get("/api/ld/quizzes/{quiz_id}/attempts")
def list_quiz_attempts(quiz_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    if user["role"] == "employee":
        rows = conn.execute(
            "SELECT * FROM ld_quiz_attempts WHERE quiz_id=? AND institution_id=? AND employee_id=? ORDER BY attempt_number",
            (quiz_id, inst_id, user.get("employee_id") or "")
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM ld_quiz_attempts WHERE quiz_id=? AND institution_id=? ORDER BY employee_id, attempt_number",
            (quiz_id, inst_id)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ---------------------------------------------------------------------------
# Learning & Development — Course Modules (content)
# ---------------------------------------------------------------------------
@app.get("/api/ld/courses/{course_id}/modules")
def list_course_modules(course_id: int, enrollment_id: Optional[int] = None,
                        user: dict = Depends(get_current_user)):
    """Course content. If enrollment_id given, includes per-module viewed flags."""
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute("SELECT id FROM ld_courses WHERE id=? AND institution_id=?", (course_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Course not found")
    rows = conn.execute(
        "SELECT * FROM ld_course_modules WHERE course_id=? AND institution_id=? ORDER BY order_index",
        (course_id, inst_id)
    ).fetchall()
    modules = [dict(r) for r in rows]
    if enrollment_id:
        viewed = {r["module_id"] for r in conn.execute(
            "SELECT module_id FROM ld_lesson_progress WHERE enrollment_id=? AND institution_id=?",
            (enrollment_id, inst_id)
        ).fetchall()}
        for m in modules:
            m["viewed"] = m["id"] in viewed
    conn.close()
    return modules

@app.put("/api/ld/courses/{course_id}/modules")
def replace_course_modules(course_id: int, body: LDModulesIn,
                           user: dict = Depends(require_roles(*LD_MANAGE_ROLES))):
    """Replace the full ordered module list for a course (same upsert pattern as the quiz)."""
    inst_id = need_inst(user)
    for m in body.modules:
        if m.content_type not in ("text", "video"):
            raise HTTPException(400, "content_type must be text or video")
    conn = get_db()
    if not conn.execute("SELECT id FROM ld_courses WHERE id=? AND institution_id=?", (course_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Course not found")
    conn.execute(
        "DELETE FROM ld_lesson_progress WHERE module_id IN (SELECT id FROM ld_course_modules WHERE course_id=? AND institution_id=?)",
        (course_id, inst_id)
    )
    conn.execute("DELETE FROM ld_course_modules WHERE course_id=? AND institution_id=?", (course_id, inst_id))
    for idx, m in enumerate(body.modules):
        conn.execute(
            "INSERT INTO ld_course_modules (institution_id,course_id,title,content_type,content,order_index) VALUES (?,?,?,?,?,?)",
            (inst_id, course_id, m.title, m.content_type, m.content, idx)
        )
    conn.commit()
    rows = conn.execute(
        "SELECT * FROM ld_course_modules WHERE course_id=? AND institution_id=? ORDER BY order_index",
        (course_id, inst_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/ld/enrollments/{enr_id}/modules/{module_id}/viewed", status_code=201)
def mark_module_viewed(enr_id: int, module_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    enr = conn.execute("SELECT * FROM ld_enrollments WHERE id=? AND institution_id=?", (enr_id, inst_id)).fetchone()
    if not enr:
        conn.close(); raise HTTPException(404, "Enrollment not found")
    if user["role"] == "employee" and user.get("employee_id") != enr["employee_id"]:
        conn.close(); raise HTTPException(403, "Access denied")
    mod = conn.execute(
        "SELECT id FROM ld_course_modules WHERE id=? AND course_id=? AND institution_id=?",
        (module_id, enr["course_id"], inst_id)
    ).fetchone()
    if not mod:
        conn.close(); raise HTTPException(404, "Module not found for this course")
    try:
        conn.execute(
            "INSERT INTO ld_lesson_progress (institution_id,enrollment_id,module_id,employee_id) VALUES (?,?,?,?)",
            (inst_id, enr_id, module_id, enr["employee_id"])
        )
        conn.commit()
    except IntegrityError:
        conn.rollback()  # already viewed — idempotent
    conn.close()
    return {"ok": True}

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

# ---------------------------------------------------------------------------
# Dashboard To-Do List — personal items only (about the logged-in user's own
# data), not approval/task queues that belong to other people's requests.
# Computed on every request from live state (not stored), so items disappear
# automatically once actioned. Excluded for superadmin (no personal employee record).
# ---------------------------------------------------------------------------
@app.get("/api/todos")
def get_todos(user: dict = Depends(get_current_user)):
    role = user["role"]
    if role == "superadmin":
        return []
    inst_id = need_inst(user)
    conn = get_db()
    emp_id = user.get("employee_id")
    todos = []

    if emp_id:
        today = datetime.now(timezone.utc).date()
        monday = (today - timedelta(days=today.weekday())).isoformat()
        row = conn.execute(
            "SELECT id FROM timesheets WHERE institution_id=? AND employee_id=? AND period_start=? AND status='Draft'",
            (inst_id, emp_id, monday)
        ).fetchone()
        if row:
            todos.append({"key": "timesheet-my", "label": "Your timesheet for this week hasn't been submitted yet", "page": "timesheet-my", "count": 1})

        cnt = conn.execute(
            "SELECT COUNT(*) FROM ld_enrollments WHERE institution_id=? AND employee_id=? AND status='In Progress'",
            (inst_id, emp_id)
        ).fetchone()[0]
        if cnt:
            todos.append({"key": "ld-trainings", "label": f"{cnt} training course{'s' if cnt != 1 else ''} in progress", "page": "ld-trainings", "count": cnt})

        if role in ("manager", "hr_manager"):
            frag, fp = _subordinates_in_clause(inst_id, emp_id)
            cnt = conn.execute(f"""
                SELECT COUNT(*) FROM appraisals a
                WHERE a.institution_id=? AND a.status='ManagerReview' AND a.employee_id != ?
                  AND a.employee_id IN {frag}
            """, (inst_id, emp_id, *fp)).fetchone()[0]
            if cnt:
                todos.append({"key": "perf-team", "label": f"{cnt} appraisal{'s' if cnt != 1 else ''} awaiting your manager review", "page": "perf-team", "count": cnt})

    conn.close()
    return todos

# Timesheets routes now live in routers/timesheets.py, mounted above via
# app.include_router(timesheets_router).

# ---------------------------------------------------------------------------
# Payroll (Malaysia, salaried employees — Phase 1)
# payroll_manager: create/edit/finalize runs, export bank CSV.
# hr_manager: view-only (all runs/payslips, no mutation).
# Everyone with an employee record: view/print their own payslips.
# ---------------------------------------------------------------------------
PAYROLL_MANAGE_ROLES = ("payroll_manager",)
PAYROLL_VIEW_ROLES   = ("payroll_manager", "hr_manager")

def _employee_age(dob_str):
    if not dob_str:
        return 30  # sensible default if DOB missing, so calculators don't crash
    try:
        dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
    except ValueError:
        return 30
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

# Simplified monthly normal-hours threshold (8hrs x 22 working days) used to split
# Hourly employees' approved timesheet hours into regular vs. overtime (1.5x rate).
# This is an approximation — Malaysia's Employment Act overtime rules are based on
# daily/weekly limits, not a flat monthly figure; verify before relying on it.
MONTHLY_NORMAL_HOURS = 176.0
OVERTIME_MULTIPLIER = 1.5

def _compute_pay(conn, inst_id, emp, period_start, period_end):
    """Returns (basic_salary, unpaid_days, unpaid_deduction, regular_hours, overtime_hours, overtime_pay, gross_pay)."""
    salary_type = emp["salary_type"] or "Monthly"

    if salary_type == "Hourly":
        approved_hours = conn.execute("""
            SELECT COALESCE(SUM(te.hours), 0) FROM timesheet_entries te
            JOIN timesheets t ON t.id = te.timesheet_id
            WHERE t.institution_id=? AND t.employee_id=? AND t.status='Approved'
              AND te.date >= ? AND te.date <= ?
        """, (inst_id, emp["employee_id"], period_start, period_end)).fetchone()[0]
        approved_hours = float(approved_hours or 0)
        hourly_rate = emp["hourly_rate"] or 0.0
        regular_hours = min(approved_hours, MONTHLY_NORMAL_HOURS)
        overtime_hours = max(0.0, approved_hours - MONTHLY_NORMAL_HOURS)
        basic_salary = round(regular_hours * hourly_rate, 2)
        overtime_pay = round(overtime_hours * hourly_rate * OVERTIME_MULTIPLIER, 2)
        gross_pay = round(basic_salary + overtime_pay, 2)
        return basic_salary, 0.0, 0.0, regular_hours, overtime_hours, overtime_pay, gross_pay

    basic_salary = emp["basic_salary"] or 0.0
    # Unpaid-leave deduction: sum days_count of Approved leave in unpaid leave types
    # that overlaps this period.
    unpaid_days = conn.execute("""
        SELECT COALESCE(SUM(a.days_count), 0) FROM leave_applications a
        JOIN leave_types lt ON lt.id = a.leave_type_id
        WHERE a.institution_id=? AND a.employee_id=? AND a.status='Approved' AND lt.is_paid=0
          AND a.start_date <= ? AND a.end_date >= ?
    """, (inst_id, emp["employee_id"], period_end, period_start)).fetchone()[0]
    unpaid_days = float(unpaid_days or 0)
    daily_rate = basic_salary / 26 if basic_salary else 0.0  # 26 working days/month, common MY convention
    unpaid_deduction = round(daily_rate * unpaid_days, 2)
    gross_pay = round(basic_salary - unpaid_deduction, 2)
    return basic_salary, unpaid_days, unpaid_deduction, 0.0, 0.0, 0.0, gross_pay

def _generate_payslip(conn, inst_id, run_id, emp, period_start, period_end):
    """Compute and insert one payslip row for an employee for this run.

    Folds in any Pending performance bonus payouts for this employee — they
    were queued from a Finalized appraisal (see queue_bonus_payout) and ride
    along on the next payroll run generated for them, then get marked Applied.
    """
    salary_type = emp["salary_type"] or "Monthly"
    basic_salary, unpaid_days, unpaid_deduction, regular_hours, overtime_hours, overtime_pay, gross_pay = \
        _compute_pay(conn, inst_id, emp, period_start, period_end)

    pending_bonuses = conn.execute(
        "SELECT id, amount FROM performance_payouts WHERE institution_id=? AND employee_id=? AND payout_type='Bonus' AND status='Pending'",
        (inst_id, emp["employee_id"])
    ).fetchall()
    bonus_amount = round(sum(b["amount"] for b in pending_bonuses), 2)
    gross_pay = round(gross_pay + bonus_amount, 2)

    age = _employee_age(emp["date_of_birth"])

    epf = payroll_calc.calc_epf(gross_pay)
    socso = payroll_calc.calc_socso(gross_pay, age)
    eis = payroll_calc.calc_eis(gross_pay, age)
    tax_category = "Married" if emp["marital_status"] == "Married" else "Single"
    pcb = payroll_calc.calc_pcb(gross_pay, tax_category, emp["num_children"] or 0, epf["employee"])

    net_pay = round(gross_pay - epf["employee"] - socso["employee"] - eis["employee"] - pcb, 2)

    conn.execute("""
        INSERT INTO payslips (
            institution_id, payroll_run_id, employee_id, basic_salary, unpaid_leave_days, unpaid_leave_deduction,
            salary_type, regular_hours, overtime_hours, overtime_pay, bonus_amount,
            gross_pay, epf_employee, epf_employer, socso_employee, socso_employer, eis_employee, eis_employer, pcb, net_pay
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (inst_id, run_id, emp["employee_id"], basic_salary, unpaid_days, unpaid_deduction,
          salary_type, regular_hours, overtime_hours, overtime_pay, bonus_amount,
          gross_pay, epf["employee"], epf["employer"], socso["employee"], socso["employer"],
          eis["employee"], eis["employer"], pcb, net_pay))

    if pending_bonuses:
        ids = tuple(b["id"] for b in pending_bonuses)
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE performance_payouts SET status='Applied', payroll_run_id=?, applied_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id IN ({placeholders})",
            (run_id, *ids)
        )

@app.get("/api/payroll/runs")
def list_payroll_runs(user: dict = Depends(require_roles(*PAYROLL_VIEW_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    rows = conn.execute("""
        SELECT r.*, COUNT(p.id) AS employee_count, COALESCE(SUM(p.net_pay),0) AS total_net_pay
        FROM payroll_runs r
        LEFT JOIN payslips p ON p.payroll_run_id = r.id
        WHERE r.institution_id=?
        GROUP BY r.id ORDER BY r.period_start DESC
    """, (inst_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/payroll/runs", status_code=201)
def create_payroll_run(body: PayrollRunIn, user: dict = Depends(require_roles(*PAYROLL_MANAGE_ROLES))):
    inst_id = need_inst(user)
    if body.period_end <= body.period_start:
        raise HTTPException(400, "Period end must be after period start")
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO payroll_runs (institution_id, period_start, period_end, created_by) VALUES (?,?,?,?)",
            (inst_id, body.period_start, body.period_end, user["username"])
        )
        conn.commit()
        run = conn.execute("SELECT * FROM payroll_runs WHERE id=last_insert_rowid()").fetchone()
        employees = conn.execute(
            "SELECT * FROM employees WHERE institution_id=? AND status='Active'",
            (inst_id,)
        ).fetchall()
        for emp in employees:
            _generate_payslip(conn, inst_id, run["id"], emp, body.period_start, body.period_end)
        conn.commit()
        return dict(run)
    except IntegrityError:
        conn.rollback(); raise HTTPException(400, "A payroll run already exists for this exact period")
    finally:
        conn.close()

@app.get("/api/payroll/runs/{run_id}")
def get_payroll_run(run_id: int, user: dict = Depends(require_roles(*PAYROLL_VIEW_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    run = conn.execute("SELECT * FROM payroll_runs WHERE id=? AND institution_id=?", (run_id, inst_id)).fetchone()
    if not run: conn.close(); raise HTTPException(404, "Payroll run not found")
    payslips = conn.execute("""
        SELECT p.*, e.full_name, e.department, e.designation, e.bank_name, e.bank_account
        FROM payslips p JOIN employees e ON e.employee_id=p.employee_id AND e.institution_id=p.institution_id
        WHERE p.payroll_run_id=? ORDER BY e.full_name
    """, (run_id,)).fetchall()
    conn.close()
    result = dict(run)
    result["payslips"] = [dict(r) for r in payslips]
    return result

@app.put("/api/payroll/payslips/{payslip_id}")
def adjust_payslip(payslip_id: int, body: PayslipAdjustIn, user: dict = Depends(require_roles(*PAYROLL_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    slip = conn.execute("SELECT * FROM payslips WHERE id=? AND institution_id=?", (payslip_id, inst_id)).fetchone()
    if not slip: conn.close(); raise HTTPException(404, "Payslip not found")
    run = conn.execute("SELECT * FROM payroll_runs WHERE id=?", (slip["payroll_run_id"],)).fetchone()
    if run["status"] != "Draft":
        conn.close(); raise HTTPException(400, "Cannot edit a payslip on a Finalized run")
    if slip["salary_type"] == "Hourly":
        conn.close(); raise HTTPException(400, "Hourly payslips are computed from approved timesheets — use Recompute instead")
    emp = conn.execute("SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, slip["employee_id"])).fetchone()

    basic_salary = body.basic_salary if body.basic_salary is not None else slip["basic_salary"]
    unpaid_days = body.unpaid_leave_days if body.unpaid_leave_days is not None else slip["unpaid_leave_days"]
    daily_rate = basic_salary / 26 if basic_salary else 0.0
    unpaid_deduction = round(daily_rate * unpaid_days, 2)
    gross_pay = round(basic_salary - unpaid_deduction + (slip["bonus_amount"] or 0), 2)
    age = _employee_age(emp["date_of_birth"])
    epf = payroll_calc.calc_epf(gross_pay)
    socso = payroll_calc.calc_socso(gross_pay, age)
    eis = payroll_calc.calc_eis(gross_pay, age)
    tax_category = "Married" if emp["marital_status"] == "Married" else "Single"
    pcb = payroll_calc.calc_pcb(gross_pay, tax_category, emp["num_children"] or 0, epf["employee"])
    net_pay = round(gross_pay - epf["employee"] - socso["employee"] - eis["employee"] - pcb, 2)

    conn.execute("""
        UPDATE payslips SET basic_salary=?, unpaid_leave_days=?, unpaid_leave_deduction=?, gross_pay=?,
            epf_employee=?, epf_employer=?, socso_employee=?, socso_employer=?, eis_employee=?, eis_employer=?, pcb=?, net_pay=?
        WHERE id=?
    """, (basic_salary, unpaid_days, unpaid_deduction, gross_pay,
          epf["employee"], epf["employer"], socso["employee"], socso["employer"],
          eis["employee"], eis["employer"], pcb, net_pay, payslip_id))
    conn.commit()
    row = conn.execute("SELECT * FROM payslips WHERE id=?", (payslip_id,)).fetchone()
    conn.close()
    return dict(row)

@app.patch("/api/payroll/payslips/{payslip_id}/recompute")
def recompute_payslip(payslip_id: int, user: dict = Depends(require_roles(*PAYROLL_MANAGE_ROLES))):
    """Re-derive an Hourly payslip from currently-Approved timesheet hours for the run's period."""
    inst_id = need_inst(user)
    conn = get_db()
    slip = conn.execute("SELECT * FROM payslips WHERE id=? AND institution_id=?", (payslip_id, inst_id)).fetchone()
    if not slip: conn.close(); raise HTTPException(404, "Payslip not found")
    run = conn.execute("SELECT * FROM payroll_runs WHERE id=?", (slip["payroll_run_id"],)).fetchone()
    if run["status"] != "Draft":
        conn.close(); raise HTTPException(400, "Cannot edit a payslip on a Finalized run")
    emp = conn.execute("SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, slip["employee_id"])).fetchone()

    basic_salary, unpaid_days, unpaid_deduction, regular_hours, overtime_hours, overtime_pay, gross_pay = \
        _compute_pay(conn, inst_id, emp, run["period_start"], run["period_end"])
    gross_pay = round(gross_pay + (slip["bonus_amount"] or 0), 2)
    age = _employee_age(emp["date_of_birth"])
    epf = payroll_calc.calc_epf(gross_pay)
    socso = payroll_calc.calc_socso(gross_pay, age)
    eis = payroll_calc.calc_eis(gross_pay, age)
    tax_category = "Married" if emp["marital_status"] == "Married" else "Single"
    pcb = payroll_calc.calc_pcb(gross_pay, tax_category, emp["num_children"] or 0, epf["employee"])
    net_pay = round(gross_pay - epf["employee"] - socso["employee"] - eis["employee"] - pcb, 2)

    conn.execute("""
        UPDATE payslips SET basic_salary=?, unpaid_leave_days=?, unpaid_leave_deduction=?,
            regular_hours=?, overtime_hours=?, overtime_pay=?, gross_pay=?,
            epf_employee=?, epf_employer=?, socso_employee=?, socso_employer=?, eis_employee=?, eis_employer=?, pcb=?, net_pay=?
        WHERE id=?
    """, (basic_salary, unpaid_days, unpaid_deduction, regular_hours, overtime_hours, overtime_pay, gross_pay,
          epf["employee"], epf["employer"], socso["employee"], socso["employer"],
          eis["employee"], eis["employer"], pcb, net_pay, payslip_id))
    conn.commit()
    row = conn.execute("SELECT * FROM payslips WHERE id=?", (payslip_id,)).fetchone()
    conn.close()
    return dict(row)

@app.patch("/api/payroll/runs/{run_id}/finalize")
def finalize_payroll_run(run_id: int, user: dict = Depends(require_roles(*PAYROLL_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    run = conn.execute("SELECT * FROM payroll_runs WHERE id=? AND institution_id=?", (run_id, inst_id)).fetchone()
    if not run: conn.close(); raise HTTPException(404, "Payroll run not found")
    if run["status"] != "Draft":
        conn.close(); raise HTTPException(400, f"Run is already {run['status']}")
    conn.execute(
        "UPDATE payroll_runs SET status='Finalized', finalized_by=?, finalized_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=?",
        (user["username"], run_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM payroll_runs WHERE id=?", (run_id,)).fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/payroll/runs/{run_id}", status_code=204)
def delete_payroll_run(run_id: int, user: dict = Depends(require_roles(*PAYROLL_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    run = conn.execute("SELECT * FROM payroll_runs WHERE id=? AND institution_id=?", (run_id, inst_id)).fetchone()
    if not run: conn.close(); raise HTTPException(404, "Payroll run not found")
    if run["status"] != "Draft":
        conn.close(); raise HTTPException(400, "Cannot delete a Finalized run")
    conn.execute("DELETE FROM payslips WHERE payroll_run_id=?", (run_id,))
    conn.execute("DELETE FROM payroll_runs WHERE id=?", (run_id,))
    conn.commit(); conn.close()

@app.get("/api/payroll/runs/{run_id}/bank-csv")
def export_bank_csv(run_id: int, user: dict = Depends(require_roles(*PAYROLL_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    run = conn.execute("SELECT * FROM payroll_runs WHERE id=? AND institution_id=?", (run_id, inst_id)).fetchone()
    if not run: conn.close(); raise HTTPException(404, "Payroll run not found")
    payslips = conn.execute("""
        SELECT p.net_pay, e.full_name, e.employee_id, e.bank_name, e.bank_account
        FROM payslips p JOIN employees e ON e.employee_id=p.employee_id AND e.institution_id=p.institution_id
        WHERE p.payroll_run_id=? ORDER BY e.full_name
    """, (run_id,)).fetchall()
    conn.close()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Employee ID", "Full Name", "Bank Name", "Bank Account", "Net Pay"])
    for r in payslips:
        writer.writerow([r["employee_id"], r["full_name"], r["bank_name"] or "", r["bank_account"] or "", r["net_pay"]])
    buf.seek(0)
    filename = f"bank-file-{run['period_start']}-to-{run['period_end']}.csv"
    return StreamingResponse(buf, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})

@app.get("/api/payroll/payslips/mine")
def my_payslips(user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    emp_id = user.get("employee_id")
    if not emp_id:
        return []
    conn = get_db()
    rows = conn.execute("""
        SELECT p.*, r.period_start, r.period_end, r.status AS run_status
        FROM payslips p JOIN payroll_runs r ON r.id = p.payroll_run_id
        WHERE p.institution_id=? AND p.employee_id=? AND r.status='Finalized'
        ORDER BY r.period_start DESC
    """, (inst_id, emp_id)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/payroll/payslips/{payslip_id}")
def get_payslip(payslip_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    row = conn.execute("""
        SELECT p.*, r.period_start, r.period_end, r.status AS run_status,
               e.full_name, e.designation, e.department, e.bank_name, e.bank_account, e.ic_number
        FROM payslips p
        JOIN payroll_runs r ON r.id = p.payroll_run_id
        JOIN employees e ON e.employee_id = p.employee_id AND e.institution_id = p.institution_id
        WHERE p.id=? AND p.institution_id=?
    """, (payslip_id, inst_id)).fetchone()
    conn.close()
    if not row: raise HTTPException(404, "Payslip not found")
    if user["role"] not in PAYROLL_VIEW_ROLES and user.get("employee_id") != row["employee_id"]:
        raise HTTPException(403, "Access denied")
    return dict(row)

# ---------------------------------------------------------------------------
# Performance (Phase 1) — Cycles, Goals (KPI/OKR), Appraisal workflow
# (Self -> Manager -> HR Calibration -> Final). No payroll integration yet.
# hr_manager: creates/runs cycles, calibrates, closes cycles.
# manager: reviews self + downstream reporting chain (reuses employee subordinate helpers).
# employee: sets own goals, self-reviews, views own appraisal history.
# superadmin: excluded, consistent with the rest of the app.
# ---------------------------------------------------------------------------
PERFORMANCE_MANAGE_ROLES = ("hr_manager",)

def _bucket_score(ratio: float) -> int:
    if ratio >= 1.15: return 5
    if ratio >= 1.00: return 4
    if ratio >= 0.85: return 3
    if ratio >= 0.70: return 2
    return 1

def _score_goal(conn, goal) -> Optional[float]:
    if goal["goal_type"] == "KPI":
        if not goal["target_value"] or goal["actual_value"] is None:
            return None
        return float(_bucket_score(goal["actual_value"] / goal["target_value"]))
    krs = conn.execute("SELECT * FROM okr_key_results WHERE goal_id=?", (goal["id"],)).fetchall()
    if not krs:
        return None
    ratios = [(kr["actual_value"] / kr["target_value"]) if kr["target_value"] else 0.0 for kr in krs]
    return float(_bucket_score(sum(ratios) / len(ratios)))

def _compute_weighted_rating(conn, cycle_id, employee_id) -> Optional[float]:
    goals = conn.execute("SELECT * FROM goals WHERE cycle_id=? AND employee_id=?", (cycle_id, employee_id)).fetchall()
    total_weight, weighted_sum = 0.0, 0.0
    for g in goals:
        s = _score_goal(conn, g)
        if s is None:
            continue
        w = g["weight"] or 0
        total_weight += w
        weighted_sum += w * s
    if total_weight <= 0:
        return None
    return round(weighted_sum / total_weight, 2)

def _can_access_employee_performance(conn, inst_id, user, employee_id) -> bool:
    if user["role"] == "hr_manager":
        return True
    if user.get("employee_id") == employee_id:
        return True
    if user["role"] == "manager":
        return _is_self_or_subordinate(conn, inst_id, user.get("employee_id"), employee_id)
    return False

def _log_appraisal(conn, inst_id, appraisal_id, employee_id, action, detail, user):
    conn.execute(
        "INSERT INTO appraisal_audit_log (institution_id,appraisal_id,employee_id,action,detail,performed_by,performer_role) VALUES (?,?,?,?,?,?,?)",
        (inst_id, appraisal_id, employee_id, action, detail, user["username"], user["role"])
    )

# --- Cycles ---
@app.get("/api/performance/cycles")
def list_performance_cycles(user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    if user["role"] == "superadmin":
        return []
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM performance_cycles WHERE institution_id=? ORDER BY period_start DESC", (inst_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/performance/cycles", status_code=201)
def create_performance_cycle(body: PerformanceCycleIn, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    if body.period_end <= body.period_start:
        raise HTTPException(400, "Period end must be after period start")
    conn = get_db()
    conn.execute(
        "INSERT INTO performance_cycles (institution_id,name,period_start,period_end,created_by) VALUES (?,?,?,?,?)",
        (inst_id, body.name, body.period_start, body.period_end, user["username"])
    )
    conn.commit()
    row = conn.execute("SELECT * FROM performance_cycles WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)

@app.patch("/api/performance/cycles/{cycle_id}/activate")
def activate_performance_cycle(cycle_id: int, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    cycle = conn.execute("SELECT * FROM performance_cycles WHERE id=? AND institution_id=?", (cycle_id, inst_id)).fetchone()
    if not cycle: conn.close(); raise HTTPException(404, "Cycle not found")
    if cycle["status"] != "Draft":
        conn.close(); raise HTTPException(400, f"Cycle is already {cycle['status']}")
    employees = conn.execute("SELECT employee_id FROM employees WHERE institution_id=? AND status='Active'", (inst_id,)).fetchall()
    for e in employees:
        conn.execute(
            "INSERT INTO appraisals (institution_id,cycle_id,employee_id,status) VALUES (?,?,?,'SelfReview') ON CONFLICT (cycle_id, employee_id) DO NOTHING",
            (inst_id, cycle_id, e["employee_id"])
        )
    conn.execute("UPDATE performance_cycles SET status='Active' WHERE id=?", (cycle_id,))
    conn.commit()
    row = conn.execute("SELECT * FROM performance_cycles WHERE id=?", (cycle_id,)).fetchone()
    conn.close()
    return dict(row)

@app.patch("/api/performance/cycles/{cycle_id}/open-calibration")
def open_calibration(cycle_id: int, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    cycle = conn.execute("SELECT * FROM performance_cycles WHERE id=? AND institution_id=?", (cycle_id, inst_id)).fetchone()
    if not cycle: conn.close(); raise HTTPException(404, "Cycle not found")
    if cycle["status"] != "Active":
        conn.close(); raise HTTPException(400, f"Cycle must be Active to open calibration (currently {cycle['status']})")
    conn.execute("UPDATE performance_cycles SET status='Calibration' WHERE id=?", (cycle_id,))
    conn.commit()
    row = conn.execute("SELECT * FROM performance_cycles WHERE id=?", (cycle_id,)).fetchone()
    conn.close()
    return dict(row)

@app.patch("/api/performance/cycles/{cycle_id}/close")
def close_performance_cycle(cycle_id: int, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    cycle = conn.execute("SELECT * FROM performance_cycles WHERE id=? AND institution_id=?", (cycle_id, inst_id)).fetchone()
    if not cycle: conn.close(); raise HTTPException(404, "Cycle not found")
    if cycle["status"] != "Calibration":
        conn.close(); raise HTTPException(400, f"Cycle must be in Calibration to close (currently {cycle['status']})")
    not_ready = conn.execute(
        "SELECT COUNT(*) FROM appraisals WHERE cycle_id=? AND status NOT IN ('Calibration','Finalized')", (cycle_id,)
    ).fetchone()[0]
    if not_ready:
        conn.close(); raise HTTPException(400, f"{not_ready} appraisal(s) have not completed manager review yet")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        UPDATE appraisals SET
            final_rating = COALESCE(calibrated_rating, manager_rating),
            status='Finalized', finalized_by=?, finalized_at=?
        WHERE cycle_id=? AND status='Calibration'
    """, (user["username"], now, cycle_id))
    conn.execute("UPDATE performance_cycles SET status='Closed' WHERE id=?", (cycle_id,))
    conn.commit()
    row = conn.execute("SELECT * FROM performance_cycles WHERE id=?", (cycle_id,)).fetchone()
    conn.close()
    return dict(row)

# --- Goals ---
@app.get("/api/performance/goals")
def list_goals(cycle_id: int, employee_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    if user["role"] == "superadmin":
        return []
    conn = get_db()
    if employee_id:
        if not _can_access_employee_performance(conn, inst_id, user, employee_id):
            conn.close(); raise HTTPException(403, "Access denied")
        rows = conn.execute(
            "SELECT * FROM goals WHERE institution_id=? AND cycle_id=? AND employee_id=? ORDER BY created_at",
            (inst_id, cycle_id, employee_id)
        ).fetchall()
    elif user["role"] == "hr_manager":
        rows = conn.execute(
            "SELECT * FROM goals WHERE institution_id=? AND cycle_id=? ORDER BY employee_id, created_at",
            (inst_id, cycle_id)
        ).fetchall()
    elif user["role"] == "manager":
        frag, fp = _subordinates_in_clause(inst_id, user.get("employee_id", ""))
        rows = conn.execute(
            f"SELECT * FROM goals WHERE institution_id=? AND cycle_id=? AND employee_id IN {frag} ORDER BY employee_id, created_at",
            [inst_id, cycle_id, *fp]
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM goals WHERE institution_id=? AND cycle_id=? AND employee_id=? ORDER BY created_at",
            (inst_id, cycle_id, user.get("employee_id", ""))
        ).fetchall()
    result = []
    for g in rows:
        d = dict(g)
        d["score"] = _score_goal(conn, g)
        if d["goal_type"] == "OKR":
            krs = conn.execute("SELECT * FROM okr_key_results WHERE goal_id=?", (g["id"],)).fetchall()
            d["key_results"] = [dict(k) for k in krs]
        result.append(d)
    conn.close()
    return result

@app.post("/api/performance/goals", status_code=201)
def create_goal(body: GoalIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    if not _can_access_employee_performance(conn, inst_id, user, body.employee_id):
        conn.close(); raise HTTPException(403, "Access denied")
    cycle = conn.execute("SELECT * FROM performance_cycles WHERE id=? AND institution_id=?", (body.cycle_id, inst_id)).fetchone()
    if not cycle: conn.close(); raise HTTPException(404, "Cycle not found")
    if cycle["status"] != "Active":
        conn.close(); raise HTTPException(400, f"Goals can only be added while the cycle is Active (currently {cycle['status']})")
    conn.execute("""
        INSERT INTO goals (institution_id,cycle_id,employee_id,goal_type,title,description,weight,target_value,actual_value,unit,created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (inst_id, body.cycle_id, body.employee_id, body.goal_type, body.title, body.description,
          body.weight, body.target_value, body.actual_value, body.unit, user["username"]))
    conn.commit()
    row = conn.execute("SELECT * FROM goals WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)

@app.put("/api/performance/goals/{goal_id}")
def update_goal(goal_id: int, body: GoalUpdateIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    goal = conn.execute("SELECT * FROM goals WHERE id=? AND institution_id=?", (goal_id, inst_id)).fetchone()
    if not goal: conn.close(); raise HTTPException(404, "Goal not found")
    if not _can_access_employee_performance(conn, inst_id, user, goal["employee_id"]):
        conn.close(); raise HTTPException(403, "Access denied")
    cycle = conn.execute("SELECT status FROM performance_cycles WHERE id=?", (goal["cycle_id"],)).fetchone()
    if cycle["status"] != "Active":
        conn.close(); raise HTTPException(400, "Goals can only be edited while the cycle is Active")
    title = body.title if body.title is not None else goal["title"]
    description = body.description if body.description is not None else goal["description"]
    weight = body.weight if body.weight is not None else goal["weight"]
    target_value = body.target_value if body.target_value is not None else goal["target_value"]
    actual_value = body.actual_value if body.actual_value is not None else goal["actual_value"]
    unit = body.unit if body.unit is not None else goal["unit"]
    conn.execute(
        "UPDATE goals SET title=?,description=?,weight=?,target_value=?,actual_value=?,unit=? WHERE id=?",
        (title, description, weight, target_value, actual_value, unit, goal_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/performance/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    goal = conn.execute("SELECT * FROM goals WHERE id=? AND institution_id=?", (goal_id, inst_id)).fetchone()
    if not goal: conn.close(); raise HTTPException(404, "Goal not found")
    if not _can_access_employee_performance(conn, inst_id, user, goal["employee_id"]):
        conn.close(); raise HTTPException(403, "Access denied")
    cycle = conn.execute("SELECT status FROM performance_cycles WHERE id=?", (goal["cycle_id"],)).fetchone()
    if cycle["status"] != "Active":
        conn.close(); raise HTTPException(400, "Goals can only be deleted while the cycle is Active")
    conn.execute("DELETE FROM okr_key_results WHERE goal_id=?", (goal_id,))
    conn.execute("DELETE FROM goals WHERE id=?", (goal_id,))
    conn.commit(); conn.close()

@app.post("/api/performance/goals/{goal_id}/key-results", status_code=201)
def add_key_result(goal_id: int, body: KeyResultIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    goal = conn.execute("SELECT * FROM goals WHERE id=? AND institution_id=?", (goal_id, inst_id)).fetchone()
    if not goal: conn.close(); raise HTTPException(404, "Goal not found")
    if goal["goal_type"] != "OKR":
        conn.close(); raise HTTPException(400, "Key results can only be added to OKR goals")
    if not _can_access_employee_performance(conn, inst_id, user, goal["employee_id"]):
        conn.close(); raise HTTPException(403, "Access denied")
    conn.execute(
        "INSERT INTO okr_key_results (goal_id,description,target_value,actual_value) VALUES (?,?,?,?)",
        (goal_id, body.description, body.target_value, body.actual_value)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM okr_key_results WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)

@app.put("/api/performance/key-results/{kr_id}")
def update_key_result(kr_id: int, body: KeyResultIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    kr = conn.execute("SELECT * FROM okr_key_results WHERE id=?", (kr_id,)).fetchone()
    if not kr: conn.close(); raise HTTPException(404, "Key result not found")
    goal = conn.execute("SELECT * FROM goals WHERE id=?", (kr["goal_id"],)).fetchone()
    if goal["institution_id"] != inst_id or not _can_access_employee_performance(conn, inst_id, user, goal["employee_id"]):
        conn.close(); raise HTTPException(403, "Access denied")
    conn.execute(
        "UPDATE okr_key_results SET description=?,target_value=?,actual_value=? WHERE id=?",
        (body.description, body.target_value, body.actual_value, kr_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM okr_key_results WHERE id=?", (kr_id,)).fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/performance/key-results/{kr_id}", status_code=204)
def delete_key_result(kr_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    kr = conn.execute("SELECT * FROM okr_key_results WHERE id=?", (kr_id,)).fetchone()
    if not kr: conn.close(); raise HTTPException(404, "Key result not found")
    goal = conn.execute("SELECT * FROM goals WHERE id=?", (kr["goal_id"],)).fetchone()
    if goal["institution_id"] != inst_id or not _can_access_employee_performance(conn, inst_id, user, goal["employee_id"]):
        conn.close(); raise HTTPException(403, "Access denied")
    conn.execute("DELETE FROM okr_key_results WHERE id=?", (kr_id,))
    conn.commit(); conn.close()

# --- Appraisals ---
@app.get("/api/performance/appraisals")
def list_appraisals(cycle_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    if user["role"] == "superadmin":
        return []
    conn = get_db()
    base = """
        SELECT a.*, e.full_name, e.department, e.designation
        FROM appraisals a JOIN employees e ON e.employee_id=a.employee_id AND e.institution_id=a.institution_id
        WHERE a.institution_id=? AND a.cycle_id=?
    """
    if user["role"] == "hr_manager":
        rows = conn.execute(base + " ORDER BY e.full_name", (inst_id, cycle_id)).fetchall()
    elif user["role"] == "manager":
        frag, fp = _subordinates_in_clause(inst_id, user.get("employee_id", ""))
        rows = conn.execute(base + f" AND a.employee_id IN {frag} ORDER BY e.full_name", [inst_id, cycle_id, *fp]).fetchall()
    else:
        rows = conn.execute(base + " AND a.employee_id=? ORDER BY e.full_name", (inst_id, cycle_id, user.get("employee_id", ""))).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/performance/appraisals/{appraisal_id}")
def get_appraisal(appraisal_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    ap = conn.execute("""
        SELECT a.*, e.full_name, e.department, e.designation
        FROM appraisals a JOIN employees e ON e.employee_id=a.employee_id AND e.institution_id=a.institution_id
        WHERE a.id=? AND a.institution_id=?
    """, (appraisal_id, inst_id)).fetchone()
    if not ap: conn.close(); raise HTTPException(404, "Appraisal not found")
    if not _can_access_employee_performance(conn, inst_id, user, ap["employee_id"]):
        conn.close(); raise HTTPException(403, "Access denied")
    goals = conn.execute(
        "SELECT * FROM goals WHERE institution_id=? AND cycle_id=? AND employee_id=? ORDER BY created_at",
        (inst_id, ap["cycle_id"], ap["employee_id"])
    ).fetchall()
    result = dict(ap)
    goal_list, total_weight = [], 0.0
    for g in goals:
        d = dict(g)
        d["score"] = _score_goal(conn, g)
        if d["goal_type"] == "OKR":
            krs = conn.execute("SELECT * FROM okr_key_results WHERE goal_id=?", (g["id"],)).fetchall()
            d["key_results"] = [dict(k) for k in krs]
        total_weight += g["weight"] or 0
        goal_list.append(d)
    result["goals"] = goal_list
    result["total_weight"] = total_weight
    result["live_computed_rating"] = _compute_weighted_rating(conn, ap["cycle_id"], ap["employee_id"])
    conn.close()
    return result

@app.post("/api/performance/appraisals/{appraisal_id}/self-review")
def submit_self_review(appraisal_id: int, body: SelfReviewIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    ap = conn.execute("SELECT * FROM appraisals WHERE id=? AND institution_id=?", (appraisal_id, inst_id)).fetchone()
    if not ap: conn.close(); raise HTTPException(404, "Appraisal not found")
    if user.get("employee_id") != ap["employee_id"]:
        conn.close(); raise HTTPException(403, "You can only submit your own self-review")
    if ap["status"] != "SelfReview":
        conn.close(); raise HTTPException(400, f"Appraisal is not awaiting self-review (current status: {ap['status']})")
    rating = _compute_weighted_rating(conn, ap["cycle_id"], ap["employee_id"])
    conn.execute(
        "UPDATE appraisals SET self_rating=?, self_comments=?, status='ManagerReview' WHERE id=?",
        (rating, body.self_comments, appraisal_id)
    )
    _log_appraisal(conn, inst_id, appraisal_id, ap["employee_id"], "Self-Review Submitted", f"Self rating: {rating}", user)
    conn.commit()
    row = conn.execute("SELECT * FROM appraisals WHERE id=?", (appraisal_id,)).fetchone()
    conn.close()
    return dict(row)

@app.post("/api/performance/appraisals/{appraisal_id}/manager-review")
def submit_manager_review(appraisal_id: int, body: ManagerReviewIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    ap = conn.execute("SELECT * FROM appraisals WHERE id=? AND institution_id=?", (appraisal_id, inst_id)).fetchone()
    if not ap: conn.close(); raise HTTPException(404, "Appraisal not found")
    if user["role"] not in ("manager", "hr_manager"):
        conn.close(); raise HTTPException(403, "Only a manager or HR can submit a manager review")
    if user.get("employee_id") == ap["employee_id"]:
        conn.close(); raise HTTPException(403, "You cannot manager-review your own appraisal")
    if not _can_access_employee_performance(conn, inst_id, user, ap["employee_id"]):
        conn.close(); raise HTTPException(403, "Access denied")
    if ap["status"] != "ManagerReview":
        conn.close(); raise HTTPException(400, f"Appraisal is not awaiting manager review (current status: {ap['status']})")
    rating = body.manager_rating if body.manager_rating is not None else _compute_weighted_rating(conn, ap["cycle_id"], ap["employee_id"])
    conn.execute(
        "UPDATE appraisals SET manager_rating=?, manager_comments=?, status='Calibration' WHERE id=?",
        (rating, body.manager_comments, appraisal_id)
    )
    _log_appraisal(conn, inst_id, appraisal_id, ap["employee_id"], "Manager Review Submitted", f"Manager rating: {rating}", user)
    conn.commit()
    row = conn.execute("SELECT * FROM appraisals WHERE id=?", (appraisal_id,)).fetchone()
    conn.close()
    return dict(row)

@app.post("/api/performance/appraisals/{appraisal_id}/calibrate")
def calibrate_appraisal(appraisal_id: int, body: CalibrateIn, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    ap = conn.execute("SELECT * FROM appraisals WHERE id=? AND institution_id=?", (appraisal_id, inst_id)).fetchone()
    if not ap: conn.close(); raise HTTPException(404, "Appraisal not found")
    if ap["status"] != "Calibration":
        conn.close(); raise HTTPException(400, f"Appraisal is not awaiting calibration (current status: {ap['status']})")
    conn.execute(
        "UPDATE appraisals SET calibrated_rating=?, calibration_notes=? WHERE id=?",
        (body.calibrated_rating, body.calibration_notes, appraisal_id)
    )
    _log_appraisal(conn, inst_id, appraisal_id, ap["employee_id"], "Calibrated",
                    f"Calibrated rating: {body.calibrated_rating}" if body.calibrated_rating is not None else "No override", user)
    conn.commit()
    row = conn.execute("SELECT * FROM appraisals WHERE id=?", (appraisal_id,)).fetchone()
    conn.close()
    return dict(row)

# ---------------------------------------------------------------------------
# Performance -> Payroll integration (Phase 2): merit increments apply
# immediately to the employee's basic salary; bonuses are queued as Pending
# performance_payouts and get folded into gross pay the next time a payroll
# run is generated for that employee (see _generate_payslip).
# ---------------------------------------------------------------------------
@app.post("/api/performance/appraisals/{appraisal_id}/merit-increment", status_code=201)
def apply_merit_increment(appraisal_id: int, body: MeritIncrementIn, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    ap = conn.execute("SELECT * FROM appraisals WHERE id=? AND institution_id=?", (appraisal_id, inst_id)).fetchone()
    if not ap: conn.close(); raise HTTPException(404, "Appraisal not found")
    if ap["status"] != "Finalized":
        conn.close(); raise HTTPException(400, "Merit increments can only be applied to a Finalized appraisal")
    existing = conn.execute(
        "SELECT id FROM performance_payouts WHERE appraisal_id=? AND payout_type='MeritIncrement'", (appraisal_id,)
    ).fetchone()
    if existing:
        conn.close(); raise HTTPException(400, "A merit increment has already been applied for this appraisal")
    emp = conn.execute("SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, ap["employee_id"])).fetchone()
    if not emp: conn.close(); raise HTTPException(404, "Employee not found")
    old_salary = emp["basic_salary"] or 0.0
    delta = round(old_salary * body.increment_pct / 100, 2)
    new_salary = round(old_salary + delta, 2)
    conn.execute("UPDATE employees SET basic_salary=? WHERE institution_id=? AND employee_id=?", (new_salary, inst_id, ap["employee_id"]))
    conn.execute("""
        INSERT INTO performance_payouts (institution_id, appraisal_id, employee_id, payout_type, amount, increment_pct, status, created_by, applied_at)
        VALUES (?,?,?,?,?,?,?,?, to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS'))
    """, (inst_id, appraisal_id, ap["employee_id"], "MeritIncrement", delta, body.increment_pct, "Applied", user["username"]))
    write_audit(conn, user, inst_id, ap["employee_id"], emp["full_name"], "Merit Increment Applied",
                [f"Basic Salary: {old_salary:.2f} -> {new_salary:.2f} ({body.increment_pct}% via appraisal #{appraisal_id})"])
    _log_appraisal(conn, inst_id, appraisal_id, ap["employee_id"], "Merit Increment Applied",
                    f"{body.increment_pct}% (+{delta:.2f}), new basic salary {new_salary:.2f}", user)
    conn.commit()
    row = conn.execute("SELECT * FROM performance_payouts WHERE appraisal_id=? AND payout_type='MeritIncrement'", (appraisal_id,)).fetchone()
    conn.close()
    return dict(row)

@app.post("/api/performance/appraisals/{appraisal_id}/bonus", status_code=201)
def queue_bonus_payout(appraisal_id: int, body: BonusPayoutIn, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    ap = conn.execute("SELECT * FROM appraisals WHERE id=? AND institution_id=?", (appraisal_id, inst_id)).fetchone()
    if not ap: conn.close(); raise HTTPException(404, "Appraisal not found")
    if ap["status"] != "Finalized":
        conn.close(); raise HTTPException(400, "Bonuses can only be queued for a Finalized appraisal")
    conn.execute("""
        INSERT INTO performance_payouts (institution_id, appraisal_id, employee_id, payout_type, amount, status, created_by)
        VALUES (?,?,?,?,?,?,?)
    """, (inst_id, appraisal_id, ap["employee_id"], "Bonus", body.amount, "Pending", user["username"]))
    _log_appraisal(conn, inst_id, appraisal_id, ap["employee_id"], "Bonus Queued",
                    f"RM {body.amount:.2f} queued — will be added to the next payroll run", user)
    conn.commit()
    row = conn.execute(
        "SELECT * FROM performance_payouts WHERE appraisal_id=? AND payout_type='Bonus' ORDER BY id DESC LIMIT 1", (appraisal_id,)
    ).fetchone()
    conn.close()
    return dict(row)

@app.get("/api/performance/payouts")
def list_performance_payouts(status: Optional[str] = None, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES, *PAYROLL_VIEW_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    sql = """
        SELECT po.*, e.full_name, e.department, e.designation
        FROM performance_payouts po
        JOIN employees e ON e.institution_id=po.institution_id AND e.employee_id=po.employee_id
        WHERE po.institution_id=?
    """
    params = [inst_id]
    if status:
        sql += " AND po.status=?"
        params.append(status)
    sql += " ORDER BY po.created_at DESC"
    rows = conn.execute(sql, tuple(params)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.delete("/api/performance/payouts/{payout_id}", status_code=204)
def cancel_bonus_payout(payout_id: int, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    payout = conn.execute("SELECT * FROM performance_payouts WHERE id=? AND institution_id=?", (payout_id, inst_id)).fetchone()
    if not payout: conn.close(); raise HTTPException(404, "Payout not found")
    if payout["status"] != "Pending":
        conn.close(); raise HTTPException(400, "Only a Pending bonus payout can be cancelled")
    conn.execute("DELETE FROM performance_payouts WHERE id=?", (payout_id,))
    _log_appraisal(conn, inst_id, payout["appraisal_id"], payout["employee_id"], "Bonus Cancelled",
                    f"RM {payout['amount']:.2f} cancelled before payout", user)
    conn.commit()
    conn.close()

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
