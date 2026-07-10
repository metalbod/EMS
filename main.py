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

import jwt
import bcrypt
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
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
JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET environment variable is not set. A random secret is deliberately "
        "NOT generated as a fallback — that would silently invalidate all sessions on "
        "every restart, and break auth entirely across multiple worker processes/machines "
        "(each would mint a different secret). Set JWT_SECRET explicitly (see .env.example)."
    )
JWT_ALG    = "HS256"
JWT_HOURS  = 8

ROLES = ["superadmin", "hr_manager", "hr_admin", "manager", "payroll_manager", "employee"]
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

DEFAULT_OB_TEMPLATES = {
    "onboarding": [
        ("Medical / Health Check",          "Arrange pre-employment medical examination",              "hr_admin",   0),
        ("Background Check",                "Conduct background and reference verification",           "hr_admin",   1),
        ("Contract Signing",                "Issue and sign employment contract",                      "hr_manager", 2),
        ("System Account Setup",            "Create email, system logins and access cards",            "hr_admin",   3),
        ("Laptop / Equipment Allocation",   "Provision laptop and peripherals",                       "hr_admin",   4),
        ("Stationery & Supplies",           "Provide stationery kit and desk setup",                  "hr_admin",   5),
        ("Payroll & Bank Details",          "Collect bank info and register in payroll",               "hr_admin",   6),
        ("EPF / SOCSO / PCB Registration",  "Register statutory contributions",                       "hr_admin",   7),
        ("Orientation & Induction",         "Conduct company orientation session",                    "hr_manager", 8),
        ("Department Introduction",         "Introduce new hire to team and assign buddy",            "manager",    9),
        ("Welcome Acknowledgement",         "New employee signs onboarding completion form",          "employee",  10),
        # Day 1 activities
        ("Day 1: IT & Security Briefing",   "IT security policies, password rules and acceptable use","hr_admin",  11),
        ("Day 1: Workplace Safety Briefing","Evacuation routes, first aid and OSH awareness",         "hr_admin",  12),
        ("Day 1: Awareness Training",       "Complete mandatory e-learning modules (data privacy, anti-bribery, harassment)", "employee", 13),
        ("Day 1: Code of Conduct",          "Read and acknowledge the company Code of Conduct",       "employee",  14),
        ("Day 1: Employee Handbook",        "Read and acknowledge the Employee Handbook",             "employee",  15),
        ("Day 1: Company Policies",         "Briefing on leave, claims, travel and other HR policies","hr_manager",16),
        ("Day 1: Buddy / Mentor Intro",     "Meet assigned buddy or mentor for the probation period","manager",   17),
    ],
    "offboarding": [
        ("Resignation Letter Received",     "Acknowledge and accept resignation letter",               "hr_manager", 0),
        ("Exit Interview",                  "Conduct structured exit interview",                      "hr_manager", 1),
        ("Knowledge Transfer",              "Ensure handover of duties and documentation",            "manager",    2),
        ("System Access Revocation",        "Revoke all system, email and door access",               "hr_admin",   3),
        ("Return of Laptop / Equipment",    "Collect laptop, accessories and company assets",         "hr_admin",   4),
        ("Return of Stationery & Items",    "Collect stationery, pass and any company items",        "hr_admin",   5),
        ("Final Payroll Settlement",        "Process last salary, claims and encashment",             "hr_admin",   6),
        ("EPF / SOCSO Cessation",           "Notify statutory bodies of employment cessation",        "hr_admin",   7),
        ("Insurance & Benefits Termination","Remove from group insurance and benefits",               "hr_admin",   8),
        ("Reference / Certificate",         "Issue experience letter or reference if applicable",    "hr_manager", 9),
        ("Employee Acknowledgement",        "Employee signs offboarding completion checklist",       "employee",  10),
    ],
}

def seed_ob_templates(conn, inst_id: int):
    """Seed default onboarding/offboarding templates for a new institution."""
    for ob_type, items in DEFAULT_OB_TEMPLATES.items():
        existing = conn.execute(
            "SELECT COUNT(*) FROM ob_templates WHERE institution_id=? AND type=?", (inst_id, ob_type)
        ).fetchone()[0]
        if existing == 0:
            for title, desc, role, idx in items:
                conn.execute(
                    "INSERT INTO ob_templates (institution_id,type,title,description,assigned_role,order_index) VALUES (?,?,?,?,?,?)",
                    (inst_id, ob_type, title, desc, role, idx)
                )

def hash_password(p): return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()
def verify_password(p, h): return bcrypt.checkpw(p.encode(), h.encode())

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

bearer = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# App + CORS
# ---------------------------------------------------------------------------
app = FastAPI(title="EMS Multi-Tenant")

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
            basic_salary        REAL    NOT NULL DEFAULT 0,
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
            salary_min          REAL,
            salary_max          REAL,
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
            expected_salary         REAL,
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
            salary_offered      REAL,
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
            cost            REAL    NOT NULL DEFAULT 0,
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
            basic_salary        REAL    NOT NULL DEFAULT 0,
            unpaid_leave_days   REAL    NOT NULL DEFAULT 0,
            unpaid_leave_deduction REAL NOT NULL DEFAULT 0,
            gross_pay           REAL    NOT NULL DEFAULT 0,
            epf_employee        REAL    NOT NULL DEFAULT 0,
            epf_employer        REAL    NOT NULL DEFAULT 0,
            socso_employee      REAL    NOT NULL DEFAULT 0,
            socso_employer      REAL    NOT NULL DEFAULT 0,
            eis_employee        REAL    NOT NULL DEFAULT 0,
            eis_employer        REAL    NOT NULL DEFAULT 0,
            pcb                 REAL    NOT NULL DEFAULT 0,
            net_pay             REAL    NOT NULL DEFAULT 0,
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
    conn.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS hourly_rate REAL NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE payslips ADD COLUMN IF NOT EXISTS salary_type TEXT NOT NULL DEFAULT 'Monthly'")
    conn.execute("ALTER TABLE payslips ADD COLUMN IF NOT EXISTS regular_hours REAL NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE payslips ADD COLUMN IF NOT EXISTS overtime_hours REAL NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE payslips ADD COLUMN IF NOT EXISTS overtime_pay REAL NOT NULL DEFAULT 0")
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
            amount          REAL    NOT NULL DEFAULT 0,
            increment_pct   REAL,
            status          TEXT    NOT NULL DEFAULT 'Pending',
            payroll_run_id  INTEGER REFERENCES payroll_runs(id),
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            applied_at      TEXT
        )
    """)
    conn.commit()
    conn.execute("ALTER TABLE payslips ADD COLUMN IF NOT EXISTS bonus_amount REAL NOT NULL DEFAULT 0")
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

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def make_token(user: dict) -> str:
    return jwt.encode({
        "sub": str(user["id"]),
        "username": user["username"],
        "role": user["role"],
        "full_name": user["full_name"],
        "institution_id": user.get("institution_id"),
        "department": user.get("department"),
        "employee_id": user["employee_id"] if "employee_id" in user else None,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_HOURS),
    }, JWT_SECRET, algorithm=JWT_ALG)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")

def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> dict:
    if not creds:
        raise HTTPException(401, "Authentication required")
    payload = decode_token(creds.credentials)
    conn = get_db()
    user = conn.execute(
        "SELECT id, username, full_name, role, roles, department, employee_id, is_active, institution_id "
        "FROM users WHERE id = ?", (payload["sub"],)
    ).fetchone()
    conn.close()
    if not user or not user["is_active"]:
        raise HTTPException(401, "User not found or inactive")
    u = dict(user)
    # users.department is a denormalized copy that can drift out of sync with
    # (or never be set from) the linked employee record. Manager-scoped
    # queries throughout the app rely on this field, so always derive it
    # fresh from employees rather than trusting the possibly-stale column.
    if u.get("employee_id") and u.get("institution_id"):
        conn2 = get_db()
        emp = conn2.execute(
            "SELECT department FROM employees WHERE institution_id=? AND employee_id=?",
            (u["institution_id"], u["employee_id"])
        ).fetchone()
        conn2.close()
        if emp and emp["department"]:
            u["department"] = emp["department"]
    # Honor a switched role from the token (see /auth/switch-role) — the DB's
    # `role` column only holds the primary role, so without this a multi-role
    # user's active-role switch would silently revert on every request.
    token_role = payload.get("role")
    if token_role and token_role != u["role"]:
        allowed = [r.strip() for r in (u.get("roles") or u["role"]).split(",") if r.strip()]
        if token_role in allowed:
            u["role"] = token_role
    # Superadmin can switch institution context via X-Institution-Id header
    if u["role"] == "superadmin":
        hdr = request.headers.get("X-Institution-Id")
        u["active_institution_id"] = int(hdr) if hdr else None
    else:
        u["active_institution_id"] = u["institution_id"]
    return u

def require_roles(*allowed: str):
    def dep(user: dict = Depends(get_current_user)):
        if user["role"] not in allowed:
            raise HTTPException(403, "Insufficient permissions")
        return user
    return dep

def need_inst(user: dict) -> int:
    """Return active_institution_id or raise 400."""
    iid = user.get("active_institution_id")
    if iid is None:
        raise HTTPException(400, "Select an institution context first")
    return iid

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
MAX_LOGO_DATA_URL_LEN = 700_000  # ~500KB image after base64 overhead

def _validate_logo_url(v):
    if v is None or v == "":
        return None
    if not v.startswith("data:image/"):
        raise ValueError("logo_url must be a data:image/... URI")
    if len(v) > MAX_LOGO_DATA_URL_LEN:
        raise ValueError("Logo image is too large (max ~500KB)")
    return v

class InstitutionIn(BaseModel):
    name: str
    code: str
    contact_name: Optional[str] = None
    contact_email: str
    phone: Optional[str] = None
    address: Optional[str] = None
    plan: str = "starter"
    max_employees: int = 50
    logo_url: Optional[str] = None
    admin_username: str
    admin_full_name: str
    admin_password: str
    admin_email: Optional[str] = None

    @field_validator("logo_url")
    @classmethod
    def validate_logo_url(cls, v):
        return _validate_logo_url(v)

class InstitutionUpdate(BaseModel):
    name: str
    contact_name: Optional[str] = None
    contact_email: str
    phone: Optional[str] = None
    address: Optional[str] = None
    plan: str = "starter"
    max_employees: int = 50
    logo_url: Optional[str] = None

    @field_validator("logo_url")
    @classmethod
    def validate_logo_url(cls, v):
        return _validate_logo_url(v)

class InstStatusIn(BaseModel):
    status: str

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

class UserIn(BaseModel):
    username: str
    full_name: str
    email: Optional[str] = None
    password: str
    role: str
    roles: Optional[List[str]] = None  # multi-role list; defaults to [role]
    employee_id: Optional[str] = None
    institution_id: Optional[int] = None  # superadmin can specify

    @field_validator("role")
    @classmethod
    def val(cls, v):
        if v not in ROLES: raise ValueError(f"Role must be one of: {', '.join(ROLES)}")
        return v

class UserUpdate(BaseModel):
    full_name: str
    email: Optional[str] = None
    password: Optional[str] = None
    role: str
    roles: Optional[List[str]] = None  # multi-role list
    employee_id: Optional[str] = None
    is_active: bool = True

    @field_validator("role")
    @classmethod
    def val(cls, v):
        if v not in ROLES: raise ValueError(f"Role must be one of: {', '.join(ROLES)}")
        return v

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

class NoteIn(BaseModel):
    note_type: str = "general"
    body: str

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

class HolidayIn(BaseModel):
    name: str
    date: str  # YYYY-MM-DD
    year: int

class LeaveTypeIn(BaseModel):
    name: str
    annual_entitlement: float = 14.0
    requires_approval: bool = True
    requires_attachment: bool = False
    is_paid: bool = True
    is_active: bool = True

class LeaveBalanceAdjustIn(BaseModel):
    entitled_days: Optional[float] = None
    carried_forward_days: Optional[float] = None

class LeaveApplicationIn(BaseModel):
    employee_id: str
    leave_type_id: int
    start_date: str
    end_date: str
    reason: Optional[str] = None
    attachment: Optional[str] = None  # data:... URI, same pattern as institution logo

    @field_validator("attachment")
    @classmethod
    def validate_attachment(cls, v):
        return _validate_logo_url(v)  # reuses the data:-URI + size-cap validator

class LeaveStatusIn(BaseModel):
    status: str  # Approved | Rejected | Cancelled
    notes: Optional[str] = None

class ProjectIn(BaseModel):
    name: str
    description: Optional[str] = None
    status: str = "Active"  # Active | On Hold | Completed

class ProjectTaskIn(BaseModel):
    name: str
    description: Optional[str] = None
    estimated_hours: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str = "Not Started"  # Not Started | In Progress | Completed

class TaskAssignmentIn(BaseModel):
    employee_id: str
    start_datetime: str  # ISO datetime, e.g. 2026-07-08T09:00
    duration_hours: float  # expected effort for this member on this task

class TaskOpenToAllIn(BaseModel):
    open_to_all: bool

class NotificationIn(BaseModel):
    message: str
    start_time: str  # ISO datetime, e.g. 2026-07-08T09:00
    end_time: str

    @field_validator("message")
    @classmethod
    def validate_message(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Message is required")
        word_count = len(v.split())
        if word_count > 500:
            raise ValueError(f"Message must be 500 words or fewer (currently {word_count})")
        return v

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

class TimesheetEntryIn(BaseModel):
    project_id: int
    task_id: int
    date: str  # YYYY-MM-DD
    hours: float
    description: Optional[str] = None

class TimesheetStartIn(BaseModel):
    employee_id: str
    period_start: str
    period_end: str

class TimesheetStatusIn(BaseModel):
    status: str  # Submitted | Approved | Rejected
    notes: Optional[str] = None

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

# ---------------------------------------------------------------------------
# Institution routes (superadmin only)
# ---------------------------------------------------------------------------
@app.get("/api/institutions")
def list_institutions(user: dict = Depends(require_roles("superadmin"))):
    conn = get_db()
    rows = conn.execute("""
        SELECT i.*,
               COUNT(DISTINCT e.id)  AS employee_count,
               COUNT(DISTINCT u.id)  AS user_count
        FROM   institutions i
        LEFT JOIN employees e ON e.institution_id = i.id
        LEFT JOIN users     u ON u.institution_id = i.id
        GROUP BY i.id
        ORDER BY i.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/institutions", status_code=201)
def create_institution(body: InstitutionIn, user: dict = Depends(require_roles("superadmin"))):
    conn = get_db()
    try:
        code = body.code.upper()
        if conn.execute("SELECT id FROM institutions WHERE code=?", (code,)).fetchone():
            raise HTTPException(400, "Institution code already exists")
        if conn.execute("SELECT id FROM users WHERE username=?", (body.admin_username,)).fetchone():
            raise HTTPException(400, "Admin username already taken")
        conn.execute("""
            INSERT INTO institutions (name, code, contact_name, contact_email, phone, address, plan, max_employees, logo_url)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (body.name, code, body.contact_name, body.contact_email,
              body.phone, body.address, body.plan, body.max_employees, body.logo_url))
        inst_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("""
            INSERT INTO users (institution_id, username, full_name, email, password_hash, role)
            VALUES (?,?,?,?,?,'hr_manager')
        """, (inst_id, body.admin_username, body.admin_full_name,
              body.admin_email, hash_password(body.admin_password)))
        seed_ob_templates(conn, inst_id)
        conn.commit()
        row = conn.execute("""
            SELECT i.*, 0 AS employee_count, 1 AS user_count
            FROM institutions i WHERE i.id=?
        """, (inst_id,)).fetchone()
        return dict(row)
    except IntegrityError as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        conn.close()

@app.get("/api/institutions/{inst_id}")
def get_institution(inst_id: int, user: dict = Depends(require_roles("superadmin"))):
    conn = get_db()
    row = conn.execute("""
        SELECT i.*,
               COUNT(DISTINCT e.id) AS employee_count,
               COUNT(DISTINCT u.id) AS user_count
        FROM institutions i
        LEFT JOIN employees e ON e.institution_id = i.id
        LEFT JOIN users     u ON u.institution_id = i.id
        WHERE i.id=? GROUP BY i.id
    """, (inst_id,)).fetchone()
    conn.close()
    if not row: raise HTTPException(404, "Institution not found")
    return dict(row)

@app.put("/api/institutions/{inst_id}")
def update_institution(inst_id: int, body: InstitutionUpdate, user: dict = Depends(require_roles("superadmin"))):
    conn = get_db()
    if not conn.execute("SELECT id FROM institutions WHERE id=?", (inst_id,)).fetchone():
        conn.close(); raise HTTPException(404, "Institution not found")
    conn.execute("""
        UPDATE institutions SET name=?,contact_name=?,contact_email=?,phone=?,address=?,plan=?,max_employees=?,logo_url=?
        WHERE id=?
    """, (body.name, body.contact_name, body.contact_email, body.phone,
          body.address, body.plan, body.max_employees, body.logo_url, inst_id))
    conn.commit()
    row = conn.execute("SELECT * FROM institutions WHERE id=?", (inst_id,)).fetchone()
    conn.close()
    return dict(row)

@app.patch("/api/institutions/{inst_id}/status")
def toggle_inst_status(inst_id: int, body: InstStatusIn, user: dict = Depends(require_roles("superadmin"))):
    if body.status not in ("Active", "Suspended"):
        raise HTTPException(400, "Status must be Active or Suspended")
    conn = get_db()
    conn.execute("UPDATE institutions SET status=? WHERE id=?", (body.status, inst_id))
    conn.commit()
    row = conn.execute("SELECT * FROM institutions WHERE id=?", (inst_id,)).fetchone()
    conn.close()
    return dict(row)

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

def _subordinates_in_clause(inst_id, manager_employee_id):
    """SQL fragment + params for 'employee_id IN (manager + their full downstream reporting chain)'.
    Usage: frag, fp = _subordinates_in_clause(inst_id, mgr_id); q += f" AND e.employee_id IN {frag}"; p.extend(fp)"""
    frag = """(
        WITH RECURSIVE subordinates AS (
            SELECT employee_id FROM employees WHERE institution_id=? AND employee_id=?
            UNION ALL
            SELECT e2.employee_id FROM employees e2
            JOIN subordinates s ON e2.reports_to = s.employee_id
            WHERE e2.institution_id=?
        )
        SELECT employee_id FROM subordinates
    )"""
    return frag, [inst_id, manager_employee_id, inst_id]

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

# ---------------------------------------------------------------------------
# Org chart
# ---------------------------------------------------------------------------
@app.get("/api/org-chart")
def get_org_chart(user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    rows = conn.execute("""
        SELECT e.employee_id, e.full_name, e.designation, e.department,
               e.status, e.reports_to, m.full_name AS manager_name
        FROM employees e
        LEFT JOIN employees m ON m.institution_id = e.institution_id AND m.employee_id = e.reports_to
        WHERE e.institution_id = ?
        ORDER BY e.full_name
    """, (inst_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ---------------------------------------------------------------------------
# Audit log routes
# ---------------------------------------------------------------------------
@app.get("/api/audit-logs")
def list_audit_logs(
    employee_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 200,
    user: dict = Depends(require_roles("superadmin","hr_manager")),
):
    inst_id = need_inst(user)
    conn = get_db()
    q = "SELECT * FROM audit_logs WHERE institution_id=?"
    p = [inst_id]
    if employee_id: q += " AND target_employee_id=?"; p.append(employee_id)
    if action:      q += " AND action=?";             p.append(action)
    q += " ORDER BY timestamp DESC LIMIT ?"
    p.append(limit)
    rows = conn.execute(q, p).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["changes"] = json.loads(d["changes"]) if d["changes"] else []
        result.append(d)
    return result

# ---------------------------------------------------------------------------
# User management routes
# ---------------------------------------------------------------------------
CAN_MANAGE_USERS = ("superadmin","hr_manager")

@app.get("/api/users")
def list_users(user: dict = Depends(require_roles(*CAN_MANAGE_USERS))):
    conn = get_db()
    if user["role"] == "superadmin":
        inst_id = user.get("active_institution_id")
        if inst_id:
            rows = conn.execute(
                "SELECT id,institution_id,username,full_name,email,role,roles,employee_id,is_active,created_at "
                "FROM users WHERE institution_id=? ORDER BY created_at DESC", (inst_id,)
            ).fetchall()
        else:
            # Global view — return all non-superadmin users with institution info
            rows = conn.execute("""
                SELECT u.id, u.institution_id, u.username, u.full_name, u.email, u.role, u.roles,
                       u.employee_id, u.is_active, u.created_at,
                       i.name AS institution_name, i.code AS institution_code
                FROM users u
                LEFT JOIN institutions i ON i.id = u.institution_id
                ORDER BY u.created_at DESC
            """).fetchall()
    else:
        inst_id = user["institution_id"]
        rows = conn.execute(
            "SELECT id,institution_id,username,full_name,email,role,roles,employee_id,is_active,created_at "
            "FROM users WHERE institution_id=? ORDER BY created_at DESC", (inst_id,)
        ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["roles"] = [x.strip() for x in (d.get("roles") or d["role"]).split(",") if x.strip()]
        result.append(d)
    return result

@app.post("/api/users", status_code=201)
def create_user(body: UserIn, user: dict = Depends(require_roles(*CAN_MANAGE_USERS))):
    # Determine which institution this user belongs to
    if user["role"] == "superadmin":
        inst_id = body.institution_id or user.get("active_institution_id")
        if body.role != "superadmin" and inst_id is None:
            raise HTTPException(400, "institution_id is required when creating non-superadmin users")
        if body.role == "superadmin":
            inst_id = None  # platform-level
    else:
        if body.role == "superadmin":
            raise HTTPException(403, "HR Managers cannot create Platform Admin accounts")
        inst_id = user["institution_id"]

    roles_str = ",".join(body.roles) if body.roles else body.role
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO users (institution_id, username, full_name, email, password_hash, role, roles, employee_id)
            VALUES (?,?,?,?,?,?,?,?)
        """, (inst_id, body.username, body.full_name, body.email,
              hash_password(body.password), body.role, roles_str, body.employee_id))
        conn.commit()
        row = conn.execute(
            "SELECT id,institution_id,username,full_name,email,role,roles,employee_id,is_active,created_at "
            "FROM users WHERE username=?", (body.username,)
        ).fetchone()
        return dict(row)
    except IntegrityError:
        conn.rollback(); raise HTTPException(400, "Username already exists")
    finally:
        conn.close()

@app.put("/api/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, user: dict = Depends(require_roles(*CAN_MANAGE_USERS))):
    conn = get_db()
    target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not target: conn.close(); raise HTTPException(404, "User not found")
    if user["role"] == "hr_manager":
        if target["role"] == "superadmin": conn.close(); raise HTTPException(403, "Cannot edit Platform Admin")
        if body.role == "superadmin":      conn.close(); raise HTTPException(403, "Cannot assign Platform Admin role")
        if target["institution_id"] != user["institution_id"]:
            conn.close(); raise HTTPException(403, "Access denied to this user")
    if user_id == user["id"] and body.role != user["role"]:
        conn.close(); raise HTTPException(400, "Cannot change your own role")
    new_hash = hash_password(body.password) if body.password else target["password_hash"]
    roles_str = ",".join(body.roles) if body.roles else body.role
    conn.execute("""
        UPDATE users SET full_name=?,email=?,password_hash=?,role=?,roles=?,employee_id=?,is_active=?
        WHERE id=?
    """, (body.full_name, body.email, new_hash, body.role, roles_str,
          body.employee_id, 1 if body.is_active else 0, user_id))
    conn.commit()
    row = conn.execute(
        "SELECT id,institution_id,username,full_name,email,role,roles,employee_id,is_active,created_at "
        "FROM users WHERE id=?", (user_id,)
    ).fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/users/{user_id}", status_code=204)
def delete_user(user_id: int, user: dict = Depends(require_roles("superadmin","hr_manager"))):
    if user_id == user["id"]:
        raise HTTPException(400, "Cannot delete your own account")
    conn = get_db()
    target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not target: conn.close(); raise HTTPException(404, "User not found")
    if user["role"] == "hr_manager" and target["institution_id"] != user["institution_id"]:
        conn.close(); raise HTTPException(403, "Access denied")
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
# HR Notes (confidential)
# ---------------------------------------------------------------------------
HR_NOTE_ROLES = ["superadmin","hr_manager","hr_admin"]

@app.get("/api/employees/{employee_id}/notes")
def get_notes(employee_id: str, user: dict = Depends(require_roles(*HR_NOTE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT id,note_type,body,created_by,created_at FROM hr_notes "
        "WHERE institution_id=? AND employee_id=? AND deleted=0 ORDER BY created_at DESC",
        (inst_id, employee_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/employees/{employee_id}/notes", status_code=201)
def create_note(employee_id: str, note: NoteIn, user: dict = Depends(require_roles(*HR_NOTE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute(
        "SELECT id FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, employee_id)
    ).fetchone():
        conn.close(); raise HTTPException(404, "Employee not found")
    conn.execute(
        "INSERT INTO hr_notes (institution_id, employee_id, note_type, body, created_by) VALUES (?,?,?,?,?)",
        (inst_id, employee_id, note.note_type, note.body.strip(), user["username"])
    )
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/api/employees/{employee_id}/notes/{note_id}", status_code=204)
def delete_note(employee_id: str, note_id: int,
                user: dict = Depends(require_roles("superadmin","hr_manager"))):
    inst_id = need_inst(user)
    conn = get_db()
    conn.execute(
        "UPDATE hr_notes SET deleted=1 WHERE id=? AND institution_id=? AND employee_id=?",
        (note_id, inst_id, employee_id)
    )
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
# Recruitment — models
# ---------------------------------------------------------------------------
CANDIDATE_STAGES  = ["New","Screening","Interview","Offer","Hired","Rejected","Withdrawn"]
INTERVIEW_TYPES   = ["Phone","Video","In-Person","Technical","Panel"]
OFFER_TYPES       = ["Offer","Decline"]
OFFER_STATUSES    = ["Draft","Sent","Accepted","Rejected","Withdrawn"]
INTERVIEW_STATUSES= ["Scheduled","Completed","Cancelled","No-Show"]
REQ_STATUSES      = ["Draft","Pending Approval","Approved","Rejected","Closed","Filled"]
PRIORITIES        = ["Low","Normal","High","Urgent"]
SOURCES           = ["Direct","JobStreet","LinkedIn","Indeed","Referral","Agency","Walk-In","Other"]
QUALIFICATIONS    = ["SPM","STPM","Diploma","Bachelor's Degree","Master's Degree","PhD","Professional Cert","Other"]
SCORE_LABELS      = ["technical_score","communication_score","attitude_score","culture_fit_score","overall_score"]

class RequisitionIn(BaseModel):
    title: str
    department: str
    headcount: int = 1
    employment_type: str = "Permanent"
    description: Optional[str] = None
    requirements: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    priority: str = "Normal"

class RequisitionApprovalIn(BaseModel):
    action: str   # approve | reject
    comments: Optional[str] = None

class CandidateIn(BaseModel):
    requisition_id: Optional[int] = None
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    ic_number: Optional[str] = None
    nationality: str = "Malaysian"
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    address: Optional[str] = None
    current_position: Optional[str] = None
    current_company: Optional[str] = None
    experience_years: int = 0
    employment_history: Optional[str] = None
    highest_qualification: Optional[str] = None
    field_of_study: Optional[str] = None
    institution_name: Optional[str] = None
    graduation_year: Optional[int] = None
    certifications: Optional[str] = None
    skills: Optional[str] = None
    source: str = "Direct"
    resume_text: Optional[str] = None
    expected_salary: Optional[float] = None
    notice_period: Optional[str] = None
    linkedin_url: Optional[str] = None
    referral_by: Optional[str] = None
    notes: Optional[str] = None

class CandidateStageIn(BaseModel):
    stage: str
    notes: Optional[str] = None

class InterviewIn(BaseModel):
    candidate_id: int
    requisition_id: Optional[int] = None
    interview_type: str = "In-Person"
    scheduled_date: str
    scheduled_time: str
    duration_mins: int = 60
    location: Optional[str] = None
    interviewers: Optional[str] = None
    notes: Optional[str] = None

class InterviewStatusIn(BaseModel):
    status: str
    notes: Optional[str] = None

class ScoreIn(BaseModel):
    technical_score: Optional[int] = None
    communication_score: Optional[int] = None
    attitude_score: Optional[int] = None
    culture_fit_score: Optional[int] = None
    overall_score: Optional[int] = None
    recommendation: str = "Maybe"
    comments: Optional[str] = None

class OfferIn(BaseModel):
    candidate_id: int
    requisition_id: Optional[int] = None
    offer_type: str = "Offer"
    salary_offered: Optional[float] = None
    start_date: Optional[str] = None
    expiry_date: Optional[str] = None
    letter_content: Optional[str] = None

class OfferStatusIn(BaseModel):
    status: str

# ---------------------------------------------------------------------------
# Recruitment — helpers
# ---------------------------------------------------------------------------
RECRUIT_WRITE = ("superadmin","hr_manager","hr_admin")

def _log_candidate(conn, inst_id: int, cand_id: int, action: str, detail: str, by: str):
    conn.execute(
        "INSERT INTO candidate_audit_log (institution_id,candidate_id,action,detail,performed_by) VALUES (?,?,?,?,?)",
        (inst_id, cand_id, action, detail, by)
    )

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

def _log_leave(conn, inst_id: int, app_id: int, emp_id: str,
               action: str, detail: str, user: dict):
    conn.execute(
        """INSERT INTO leave_audit_log
           (institution_id,application_id,employee_id,action,detail,performed_by,performer_role)
           VALUES (?,?,?,?,?,?,?)""",
        (inst_id, app_id, emp_id, action, detail, user["username"], user["role"])
    )

def _compute_leave_days(conn, inst_id: int, start_date: str, end_date: str) -> float:
    """Counts weekdays (Mon-Fri) in the inclusive range, excluding institution public holidays."""
    d0 = datetime.strptime(start_date, "%Y-%m-%d").date()
    d1 = datetime.strptime(end_date, "%Y-%m-%d").date()
    if d1 < d0:
        raise HTTPException(400, "End date must be on or after start date")
    holiday_rows = conn.execute(
        "SELECT date FROM holidays WHERE institution_id=? AND date BETWEEN ? AND ?",
        (inst_id, start_date, end_date)
    ).fetchall()
    holiday_dates = {r["date"] for r in holiday_rows}
    count = 0
    d = d0
    while d <= d1:
        ds = d.strftime("%Y-%m-%d")
        if d.weekday() < 5 and ds not in holiday_dates:
            count += 1
        d += timedelta(days=1)
    return float(count)

def _get_or_create_leave_balance(conn, inst_id: int, employee_id: str, leave_type_id: int, year: int):
    row = conn.execute(
        "SELECT * FROM leave_balances WHERE employee_id=? AND leave_type_id=? AND year=?",
        (employee_id, leave_type_id, year)
    ).fetchone()
    if row:
        return row
    lt = conn.execute("SELECT * FROM leave_types WHERE id=? AND institution_id=?", (leave_type_id, inst_id)).fetchone()
    entitled = lt["annual_entitlement"] if lt else 0
    conn.execute(
        "INSERT INTO leave_balances (institution_id,employee_id,leave_type_id,year,entitled_days,carried_forward_days,used_days) VALUES (?,?,?,?,?,0,0)",
        (inst_id, employee_id, leave_type_id, year, entitled)
    )
    return conn.execute(
        "SELECT * FROM leave_balances WHERE employee_id=? AND leave_type_id=? AND year=?",
        (employee_id, leave_type_id, year)
    ).fetchone()

def _log_timesheet(conn, inst_id: int, ts_id: int, emp_id: str,
                    action: str, detail: str, user: dict):
    conn.execute(
        """INSERT INTO timesheet_audit_log
           (institution_id,timesheet_id,employee_id,action,detail,performed_by,performer_role)
           VALUES (?,?,?,?,?,?,?)""",
        (inst_id, ts_id, emp_id, action, detail, user["username"], user["role"])
    )

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

def _get_candidate(conn, inst_id, cand_id):
    row = conn.execute(
        "SELECT * FROM candidates WHERE id=? AND institution_id=?", (cand_id, inst_id)
    ).fetchone()
    if not row: raise HTTPException(404, "Candidate not found")
    return dict(row)

def _get_req(conn, inst_id, req_id):
    row = conn.execute(
        "SELECT * FROM job_requisitions WHERE id=? AND institution_id=?", (req_id, inst_id)
    ).fetchone()
    if not row: raise HTTPException(404, "Requisition not found")
    return dict(row)

def _gen_offer_letter(cand, req, offer):
    today = datetime.now().strftime("%d %B %Y")
    if offer["offer_type"] == "Offer":
        salary_line = f"Basic Salary: RM {offer['salary_offered']:,.2f} per month" if offer.get("salary_offered") else ""
        start_line  = f"Commencement Date: {offer['start_date']}" if offer.get("start_date") else ""
        expiry_line = f"This offer is valid until {offer['expiry_date']}." if offer.get("expiry_date") else ""
        req_title   = req.get("title","") if req else ""
        req_dept    = req.get("department","") if req else ""
        emp_type    = req.get("employment_type","") if req else ""
        return f"""[COMPANY LETTERHEAD]

{today}

{cand['full_name']}
{cand.get('email','') or ''}

Dear {cand['full_name']},

LETTER OF OFFER — {req_title.upper()}

We are pleased to offer you the position of {req_title} in the {req_dept} department on the following terms and conditions:

Position        : {req_title}
Department      : {req_dept}
Employment Type : {emp_type}
{salary_line}
{start_line}

Your appointment will be subject to:
1. Satisfactory completion of our pre-employment medical examination.
2. Submission of all required original documents for verification.
3. Compliance with the Company's policies, rules and regulations.

{expiry_line}

To accept this offer, please sign and return one copy of this letter by the expiry date stated above.

We look forward to welcoming you to our team.

Yours sincerely,


_______________________
Human Resources
[Company Name]


I, {cand['full_name']}, hereby accept the above offer of employment.

Signature: _______________________    Date: _______________
"""
    else:
        req_title = req.get("title","the position") if req else "the position"
        return f"""[COMPANY LETTERHEAD]

{today}

{cand['full_name']}
{cand.get('email','') or ''}

Dear {cand['full_name']},

RE: Application for {req_title}

Thank you for your interest in the above position and for the time you invested in our recruitment process.

After careful consideration of all applications received, we regret to inform you that we are unable to offer you a position at this time. This was a difficult decision as we received many strong applications.

We appreciate the effort you put into your application and encourage you to apply for future vacancies that match your profile.

We wish you every success in your career endeavours.

Yours sincerely,


_______________________
Human Resources
[Company Name]
"""

# ---------------------------------------------------------------------------
# Recruitment — Job Requisitions
# ---------------------------------------------------------------------------
@app.get("/api/recruitment/requisitions")
def list_requisitions(
    status: Optional[str] = None,
    department: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    inst_id = need_inst(user)
    conn = get_db()
    q = "SELECT r.*, COUNT(c.id) AS candidate_count FROM job_requisitions r LEFT JOIN candidates c ON c.requisition_id=r.id AND c.stage NOT IN ('Rejected','Withdrawn') WHERE r.institution_id=?"
    p = [inst_id]
    if status:     q += " AND r.status=?";     p.append(status)
    if department: q += " AND r.department=?"; p.append(department)
    q += " GROUP BY r.id ORDER BY r.created_at DESC"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/recruitment/requisitions", status_code=201)
def create_requisition(body: RequisitionIn, user: dict = Depends(require_roles(*RECRUIT_WRITE))):
    inst_id = need_inst(user)
    conn = get_db()
    conn.execute("""
        INSERT INTO job_requisitions (institution_id,title,department,headcount,employment_type,
            description,requirements,salary_min,salary_max,priority,created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (inst_id, body.title, body.department, body.headcount, body.employment_type,
          body.description, body.requirements, body.salary_min, body.salary_max,
          body.priority, user["username"]))
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    row = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (rid,)).fetchone()
    conn.close()
    return dict(row)

@app.get("/api/recruitment/requisitions/{req_id}")
def get_requisition(req_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    r = _get_req(conn, inst_id, req_id)
    cands = conn.execute(
        "SELECT id,full_name,stage,source,created_at FROM candidates WHERE requisition_id=? AND institution_id=? ORDER BY created_at DESC",
        (req_id, inst_id)
    ).fetchall()
    conn.close()
    r["candidates"] = [dict(c) for c in cands]
    return r

@app.put("/api/recruitment/requisitions/{req_id}")
def update_requisition(req_id: int, body: RequisitionIn, user: dict = Depends(require_roles(*RECRUIT_WRITE))):
    inst_id = need_inst(user)
    conn = get_db()
    r = _get_req(conn, inst_id, req_id)
    if r["status"] not in ("Draft",):
        conn.close(); raise HTTPException(400, "Only Draft requisitions can be edited")
    conn.execute("""
        UPDATE job_requisitions SET title=?,department=?,headcount=?,employment_type=?,
            description=?,requirements=?,salary_min=?,salary_max=?,priority=?
        WHERE id=? AND institution_id=?
    """, (body.title, body.department, body.headcount, body.employment_type,
          body.description, body.requirements, body.salary_min, body.salary_max,
          body.priority, req_id, inst_id))
    conn.commit()
    row = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (req_id,)).fetchone()
    conn.close()
    return dict(row)

@app.patch("/api/recruitment/requisitions/{req_id}/submit")
def submit_requisition(req_id: int, user: dict = Depends(require_roles(*RECRUIT_WRITE))):
    inst_id = need_inst(user)
    conn = get_db()
    r = _get_req(conn, inst_id, req_id)
    if r["status"] != "Draft":
        conn.close(); raise HTTPException(400, "Only Draft requisitions can be submitted")
    conn.execute("UPDATE job_requisitions SET status='Pending Approval' WHERE id=?", (req_id,))
    conn.commit()
    row = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (req_id,)).fetchone()
    conn.close()
    return dict(row)

@app.patch("/api/recruitment/requisitions/{req_id}/approve")
def approve_requisition(req_id: int, body: RequisitionApprovalIn,
                         user: dict = Depends(require_roles("superadmin","hr_manager"))):
    inst_id = need_inst(user)
    conn = get_db()
    r = _get_req(conn, inst_id, req_id)
    if r["status"] != "Pending Approval":
        conn.close(); raise HTTPException(400, "Requisition is not pending approval")
    if body.action not in ("approve","reject"):
        conn.close(); raise HTTPException(400, "Action must be approve or reject")
    new_status = "Approved" if body.action == "approve" else "Rejected"
    conn.execute("""
        UPDATE job_requisitions SET status=?, approved_by=?, approval_comments=?
        WHERE id=?
    """, (new_status, user["username"], body.comments, req_id))
    conn.commit()
    row = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (req_id,)).fetchone()
    conn.close()
    return dict(row)

@app.patch("/api/recruitment/requisitions/{req_id}/close")
def close_requisition(req_id: int, user: dict = Depends(require_roles(*RECRUIT_WRITE))):
    inst_id = need_inst(user)
    conn = get_db()
    conn.execute(
        "UPDATE job_requisitions SET status='Closed', closed_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=? AND institution_id=?",
        (req_id, inst_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (req_id,)).fetchone()
    conn.close()
    return dict(row)

# ---------------------------------------------------------------------------
# Recruitment — Candidates / ATS
# ---------------------------------------------------------------------------
@app.get("/api/recruitment/candidates")
def list_candidates(
    requisition_id: Optional[int] = None,
    stage: Optional[str] = None,
    search: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    inst_id = need_inst(user)
    conn = get_db()
    q = """SELECT c.*, r.title AS requisition_title
           FROM candidates c
           LEFT JOIN job_requisitions r ON r.id = c.requisition_id
           WHERE c.institution_id=?"""
    p = [inst_id]
    if requisition_id: q += " AND c.requisition_id=?"; p.append(requisition_id)
    if stage:          q += " AND c.stage=?";           p.append(stage)
    if search:
        like = f"%{search}%"
        q += " AND (c.full_name LIKE ? OR c.email LIKE ? OR c.current_company LIKE ? OR c.skills LIKE ?)"
        p.extend([like,like,like,like])
    q += " ORDER BY c.created_at DESC"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/recruitment/candidates", status_code=201)
def create_candidate(body: CandidateIn, user: dict = Depends(require_roles(*RECRUIT_WRITE))):
    inst_id = need_inst(user)
    conn = get_db()
    conn.execute("""
        INSERT INTO candidates (institution_id,requisition_id,full_name,email,phone,ic_number,
            nationality,gender,date_of_birth,address,current_position,current_company,
            experience_years,employment_history,highest_qualification,field_of_study,
            institution_name,graduation_year,certifications,skills,source,resume_text,
            expected_salary,notice_period,linkedin_url,referral_by,notes,created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (inst_id, body.requisition_id, body.full_name, body.email, body.phone, body.ic_number,
          body.nationality, body.gender, body.date_of_birth, body.address,
          body.current_position, body.current_company, body.experience_years, body.employment_history,
          body.highest_qualification, body.field_of_study, body.institution_name, body.graduation_year,
          body.certifications, body.skills, body.source, body.resume_text,
          body.expected_salary, body.notice_period, body.linkedin_url, body.referral_by,
          body.notes, user["username"]))
    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    _log_candidate(conn, inst_id, cid, "Created", f"Candidate '{body.full_name}' added via {body.source}", user["username"])
    conn.commit()
    row = conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    conn.close()
    return dict(row)

@app.get("/api/recruitment/candidates/{cand_id}")
def get_candidate(cand_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    c = _get_candidate(conn, inst_id, cand_id)
    req = None
    if c.get("requisition_id"):
        r = conn.execute("SELECT id,title,department FROM job_requisitions WHERE id=?",
                         (c["requisition_id"],)).fetchone()
        req = dict(r) if r else None
    interviews = conn.execute("""
        SELECT i.*, STRING_AGG(s.scored_by, ',') AS scored_by_list,
               AVG(s.overall_score) AS avg_score
        FROM interviews i
        LEFT JOIN interview_scores s ON s.interview_id = i.id
        WHERE i.candidate_id=? AND i.institution_id=?
        GROUP BY i.id ORDER BY i.scheduled_date DESC, i.scheduled_time DESC
    """, (cand_id, inst_id)).fetchall()
    interview_list = [dict(i) for i in interviews]
    for iv in interview_list:
        scores = conn.execute(
            "SELECT scored_by,technical_score,communication_score,attitude_score,culture_fit_score,overall_score,recommendation,comments FROM interview_scores WHERE interview_id=? AND institution_id=? ORDER BY created_at",
            (iv["id"], inst_id)
        ).fetchall()
        iv["scores"] = [dict(s) for s in scores]
    offers = conn.execute(
        "SELECT * FROM offers WHERE candidate_id=? AND institution_id=? ORDER BY created_at DESC",
        (cand_id, inst_id)
    ).fetchall()
    conn.close()
    c["requisition"] = req
    c["interviews"] = interview_list
    c["offers"] = [dict(o) for o in offers]
    return c

@app.put("/api/recruitment/candidates/{cand_id}")
def update_candidate(cand_id: int, body: CandidateIn, user: dict = Depends(require_roles(*RECRUIT_WRITE))):
    inst_id = need_inst(user)
    conn = get_db()
    _get_candidate(conn, inst_id, cand_id)
    conn.execute("""
        UPDATE candidates SET requisition_id=?,full_name=?,email=?,phone=?,ic_number=?,
            nationality=?,gender=?,date_of_birth=?,address=?,current_position=?,current_company=?,
            experience_years=?,employment_history=?,highest_qualification=?,field_of_study=?,
            institution_name=?,graduation_year=?,certifications=?,skills=?,source=?,resume_text=?,
            expected_salary=?,notice_period=?,linkedin_url=?,referral_by=?,notes=?
        WHERE id=? AND institution_id=?
    """, (body.requisition_id, body.full_name, body.email, body.phone, body.ic_number,
          body.nationality, body.gender, body.date_of_birth, body.address,
          body.current_position, body.current_company, body.experience_years, body.employment_history,
          body.highest_qualification, body.field_of_study, body.institution_name, body.graduation_year,
          body.certifications, body.skills, body.source, body.resume_text,
          body.expected_salary, body.notice_period, body.linkedin_url, body.referral_by,
          body.notes, cand_id, inst_id))
    _log_candidate(conn, inst_id, cand_id, "Updated", "Candidate profile details updated", user["username"])
    conn.commit()
    row = conn.execute("SELECT * FROM candidates WHERE id=?", (cand_id,)).fetchone()
    conn.close()
    return dict(row)

@app.patch("/api/recruitment/candidates/{cand_id}/stage")
def move_stage(cand_id: int, body: CandidateStageIn, user: dict = Depends(require_roles(*RECRUIT_WRITE))):
    if body.stage not in CANDIDATE_STAGES:
        raise HTTPException(400, f"Stage must be one of: {', '.join(CANDIDATE_STAGES)}")
    inst_id = need_inst(user)
    conn = get_db()
    _get_candidate(conn, inst_id, cand_id)
    extra_notes = f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Stage moved to {body.stage} by {user['username']}: {body.notes or ''}".strip()
    old = _get_candidate(conn, inst_id, cand_id)
    conn.execute("""
        UPDATE candidates SET stage=?, notes=COALESCE(notes,'') || ?
        WHERE id=? AND institution_id=?
    """, (body.stage, extra_notes, cand_id, inst_id))
    detail = f"Stage changed: {old.get('stage','?')} → {body.stage}"
    if body.notes: detail += f" | Reason: {body.notes}"
    _log_candidate(conn, inst_id, cand_id, "Stage Changed", detail, user["username"])
    conn.commit()
    row = conn.execute("SELECT * FROM candidates WHERE id=?", (cand_id,)).fetchone()
    conn.close()
    return dict(row)

# ---------------------------------------------------------------------------
# Recruitment — Interviews
# ---------------------------------------------------------------------------
@app.get("/api/recruitment/interviews")
def list_interviews(
    candidate_id: Optional[int] = None,
    status: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    inst_id = need_inst(user)
    conn = get_db()
    q = """SELECT i.*, c.full_name AS candidate_name, r.title AS requisition_title,
                  COUNT(s.id) AS score_count, AVG(s.overall_score) AS avg_score
           FROM interviews i
           JOIN candidates c ON c.id = i.candidate_id
           LEFT JOIN job_requisitions r ON r.id = i.requisition_id
           LEFT JOIN interview_scores s ON s.interview_id = i.id
           WHERE i.institution_id=?"""
    p = [inst_id]
    if candidate_id: q += " AND i.candidate_id=?"; p.append(candidate_id)
    if status:       q += " AND i.status=?";       p.append(status)
    q += " GROUP BY i.id, c.full_name, r.title ORDER BY i.scheduled_date DESC, i.scheduled_time DESC"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/recruitment/interviews", status_code=201)
def schedule_interview(body: InterviewIn, user: dict = Depends(require_roles(*RECRUIT_WRITE))):
    inst_id = need_inst(user)
    conn = get_db()
    _get_candidate(conn, inst_id, body.candidate_id)
    conn.execute("""
        INSERT INTO interviews (institution_id,candidate_id,requisition_id,interview_type,
            scheduled_date,scheduled_time,duration_mins,location,interviewers,notes,created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (inst_id, body.candidate_id, body.requisition_id, body.interview_type,
          body.scheduled_date, body.scheduled_time, body.duration_mins,
          body.location, body.interviewers, body.notes, user["username"]))
    iid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Auto-move candidate to Interview stage
    conn.execute(
        "UPDATE candidates SET stage='Interview' WHERE id=? AND institution_id=? AND stage IN ('New','Screening')",
        (body.candidate_id, inst_id)
    )
    _log_candidate(conn, inst_id, body.candidate_id, "Interview Scheduled",
        f"{body.interview_type} interview on {body.scheduled_date} at {body.scheduled_time}"
        + (f" with {body.interviewers}" if body.interviewers else ""),
        user["username"])
    conn.commit()
    row = conn.execute("""
        SELECT i.*, c.full_name AS candidate_name FROM interviews i
        JOIN candidates c ON c.id = i.candidate_id WHERE i.id=?
    """, (iid,)).fetchone()
    conn.close()
    return dict(row)

@app.put("/api/recruitment/interviews/{int_id}")
def update_interview(int_id: int, body: InterviewIn, user: dict = Depends(require_roles(*RECRUIT_WRITE))):
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute("SELECT id FROM interviews WHERE id=? AND institution_id=?", (int_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Interview not found")
    conn.execute("""
        UPDATE interviews SET interview_type=?,scheduled_date=?,scheduled_time=?,
            duration_mins=?,location=?,interviewers=?,notes=?
        WHERE id=? AND institution_id=?
    """, (body.interview_type, body.scheduled_date, body.scheduled_time,
          body.duration_mins, body.location, body.interviewers, body.notes, int_id, inst_id))
    conn.commit()
    row = conn.execute("SELECT * FROM interviews WHERE id=?", (int_id,)).fetchone()
    conn.close()
    return dict(row)

@app.patch("/api/recruitment/interviews/{int_id}/status")
def update_interview_status(int_id: int, body: InterviewStatusIn,
                             user: dict = Depends(require_roles(*RECRUIT_WRITE))):
    if body.status not in INTERVIEW_STATUSES:
        raise HTTPException(400, f"Status must be one of: {', '.join(INTERVIEW_STATUSES)}")
    inst_id = need_inst(user)
    conn = get_db()
    conn.execute(
        "UPDATE interviews SET status=?, notes=COALESCE(notes||' ','') || COALESCE(?,'') WHERE id=? AND institution_id=?",
        (body.status, body.notes, int_id, inst_id)
    )
    row = conn.execute("SELECT * FROM interviews WHERE id=?", (int_id,)).fetchone()
    if row:
        _log_candidate(conn, inst_id, row["candidate_id"],
                       "Interview Status Updated",
                       f"{row['interview_type']} interview marked as {body.status}",
                       user["username"])
    conn.commit()
    conn.close()
    return dict(row)

@app.post("/api/recruitment/interviews/{int_id}/scores", status_code=201)
def submit_score(int_id: int, body: ScoreIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute("SELECT id FROM interviews WHERE id=? AND institution_id=?", (int_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Interview not found")
    cand_row = conn.execute("SELECT candidate_id FROM interviews WHERE id=?", (int_id,)).fetchone()
    try:
        conn.execute("""
            INSERT INTO interview_scores (interview_id,candidate_id,institution_id,scored_by,
                technical_score,communication_score,attitude_score,culture_fit_score,
                overall_score,recommendation,comments)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(interview_id,scored_by) DO UPDATE SET
                technical_score=excluded.technical_score,
                communication_score=excluded.communication_score,
                attitude_score=excluded.attitude_score,
                culture_fit_score=excluded.culture_fit_score,
                overall_score=excluded.overall_score,
                recommendation=excluded.recommendation,
                comments=excluded.comments
        """, (int_id, cand_row["candidate_id"], inst_id, user["username"],
              body.technical_score, body.communication_score, body.attitude_score,
              body.culture_fit_score, body.overall_score, body.recommendation, body.comments))
        conn.commit()
    except IntegrityError as e:
        conn.rollback(); raise HTTPException(400, str(e))
    finally:
        conn.close()
    return {"ok": True}

@app.get("/api/recruitment/interviews/{int_id}/scores")
def get_scores(int_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM interview_scores WHERE interview_id=? AND institution_id=? ORDER BY created_at",
        (int_id, inst_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ---------------------------------------------------------------------------
# Recruitment — Offers
# ---------------------------------------------------------------------------
@app.get("/api/recruitment/offers")
def list_offers(
    candidate_id: Optional[int] = None,
    offer_type: Optional[str] = None,
    user: dict = Depends(require_roles(*RECRUIT_WRITE)),
):
    inst_id = need_inst(user)
    conn = get_db()
    q = """SELECT o.*, c.full_name AS candidate_name, r.title AS requisition_title
           FROM offers o
           JOIN candidates c ON c.id = o.candidate_id
           LEFT JOIN job_requisitions r ON r.id = o.requisition_id
           WHERE o.institution_id=?"""
    p = [inst_id]
    if candidate_id: q += " AND o.candidate_id=?"; p.append(candidate_id)
    if offer_type:   q += " AND o.offer_type=?";  p.append(offer_type)
    q += " ORDER BY o.created_at DESC"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/recruitment/offers", status_code=201)
def create_offer(body: OfferIn, user: dict = Depends(require_roles(*RECRUIT_WRITE))):
    inst_id = need_inst(user)
    conn = get_db()
    cand = _get_candidate(conn, inst_id, body.candidate_id)
    req = None
    if body.requisition_id:
        r = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (body.requisition_id,)).fetchone()
        req = dict(r) if r else None
    # Auto-generate letter if not provided
    letter = body.letter_content or _gen_offer_letter(cand, req, body.model_dump())
    conn.execute("""
        INSERT INTO offers (institution_id,candidate_id,requisition_id,offer_type,
            salary_offered,start_date,expiry_date,letter_content,created_by)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (inst_id, body.candidate_id, body.requisition_id, body.offer_type,
          body.salary_offered, body.start_date, body.expiry_date, letter, user["username"]))
    oid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Move candidate stage
    new_stage = "Offer" if body.offer_type == "Offer" else "Rejected"
    conn.execute("UPDATE candidates SET stage=? WHERE id=? AND institution_id=?",
                 (new_stage, body.candidate_id, inst_id))
    sal = f"RM {body.salary_offered:,.0f}" if body.salary_offered else "—"
    _log_candidate(conn, inst_id, body.candidate_id, f"{body.offer_type} Letter Generated",
        f"{body.offer_type} letter created" + (f" | Salary: {sal}" if body.offer_type == "Offer" else ""),
        user["username"])
    conn.commit()
    row = conn.execute("SELECT * FROM offers WHERE id=?", (oid,)).fetchone()
    conn.close()
    return dict(row)

@app.get("/api/recruitment/offers/{offer_id}")
def get_offer(offer_id: int, user: dict = Depends(require_roles(*RECRUIT_WRITE))):
    inst_id = need_inst(user)
    conn = get_db()
    row = conn.execute(
        "SELECT o.*, c.full_name AS candidate_name FROM offers o JOIN candidates c ON c.id=o.candidate_id WHERE o.id=? AND o.institution_id=?",
        (offer_id, inst_id)
    ).fetchone()
    conn.close()
    if not row: raise HTTPException(404, "Offer not found")
    return dict(row)

@app.patch("/api/recruitment/offers/{offer_id}/status")
def update_offer_status(offer_id: int, body: OfferStatusIn,
                         user: dict = Depends(require_roles(*RECRUIT_WRITE))):
    if body.status not in OFFER_STATUSES:
        raise HTTPException(400, f"Status must be one of: {', '.join(OFFER_STATUSES)}")
    inst_id = need_inst(user)
    conn = get_db()
    row = conn.execute("SELECT * FROM offers WHERE id=? AND institution_id=?", (offer_id, inst_id)).fetchone()
    if not row: conn.close(); raise HTTPException(404, "Offer not found")
    conn.execute("UPDATE offers SET status=? WHERE id=?", (body.status, offer_id))
    # Sync candidate stage
    if body.status == "Accepted" and row["offer_type"] == "Offer":
        conn.execute("UPDATE candidates SET stage='Offer' WHERE id=? AND institution_id=?",
                     (row["candidate_id"], inst_id))
    _log_candidate(conn, inst_id, row["candidate_id"], "Offer Status Updated",
        f"{row['offer_type']} letter status changed to '{body.status}'", user["username"])
    conn.commit()
    conn.close()
    return {"ok": True, "status": body.status}

@app.post("/api/recruitment/offers/{offer_id}/generate-letter")
def generate_letter(offer_id: int, user: dict = Depends(require_roles(*RECRUIT_WRITE))):
    """Regenerate/preview offer letter text."""
    inst_id = need_inst(user)
    conn = get_db()
    row = conn.execute("SELECT * FROM offers WHERE id=? AND institution_id=?", (offer_id, inst_id)).fetchone()
    if not row: conn.close(); raise HTTPException(404, "Offer not found")
    offer = dict(row)
    cand = _get_candidate(conn, inst_id, offer["candidate_id"])
    req = None
    if offer.get("requisition_id"):
        r = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (offer["requisition_id"],)).fetchone()
        req = dict(r) if r else None
    letter = _gen_offer_letter(cand, req, offer)
    conn.execute("UPDATE offers SET letter_content=? WHERE id=?", (letter, offer_id))
    conn.commit()
    conn.close()
    return {"letter_content": letter}

@app.get("/api/recruitment/candidates/{cand_id}/convert-prefill")
def convert_to_employee_prefill(cand_id: int, user: dict = Depends(require_roles(*RECRUIT_WRITE))):
    """Return candidate data pre-formatted for the Add Employee form."""
    inst_id = need_inst(user)
    conn = get_db()
    c = _get_candidate(conn, inst_id, cand_id)
    req = None
    if c.get("requisition_id"):
        r = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (c["requisition_id"],)).fetchone()
        req = dict(r) if r else None
    # Get accepted offer for salary/start date
    offer = conn.execute(
        "SELECT * FROM offers WHERE candidate_id=? AND offer_type='Offer' AND status='Accepted' ORDER BY created_at DESC LIMIT 1",
        (cand_id,)
    ).fetchone()
    conn.close()
    return {
        "full_name":        c.get("full_name",""),
        "ic_number":        c.get("ic_number",""),
        "nationality":      c.get("nationality","Malaysian"),
        "personal_email":   c.get("email",""),
        "phone":            c.get("phone",""),
        "department":       req.get("department","") if req else "",
        "designation":      req.get("title","") if req else c.get("current_position",""),
        "employment_type":  req.get("employment_type","Permanent") if req else "Permanent",
        "basic_salary":     dict(offer).get("salary_offered",0) if offer else 0,
        "start_date":       dict(offer).get("start_date","") if offer else "",
        "candidate_id":     cand_id,
    }

@app.get("/api/recruitment/meta")
def recruitment_meta(user: dict = Depends(get_current_user)):
    return {
        "stages": CANDIDATE_STAGES,
        "interview_types": INTERVIEW_TYPES,
        "offer_types": OFFER_TYPES,
        "offer_statuses": OFFER_STATUSES,
        "interview_statuses": INTERVIEW_STATUSES,
        "req_statuses": REQ_STATUSES,
        "priorities": PRIORITIES,
        "sources": SOURCES,
        "qualifications": QUALIFICATIONS,
    }

@app.get("/api/recruitment/candidates/{cand_id}/audit-log")
def get_candidate_audit(cand_id: int, user: dict = Depends(require_roles("superadmin","hr_manager","hr_admin"))):
    inst_id = need_inst(user)
    conn = get_db()
    _get_candidate(conn, inst_id, cand_id)
    rows = conn.execute(
        "SELECT * FROM candidate_audit_log WHERE candidate_id=? AND institution_id=? ORDER BY created_at DESC",
        (cand_id, inst_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/recruitment/dashboard-stats")
def recruitment_dashboard_stats(user: dict = Depends(get_current_user)):
    iid = need_inst(user)
    conn = get_db()
    # Requisitions by status
    req_rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM job_requisitions WHERE institution_id=? GROUP BY status", (iid,)
    ).fetchall()
    req_by_status = {r["status"]: r["cnt"] for r in req_rows}

    # Candidates by stage
    cand_rows = conn.execute(
        "SELECT stage, COUNT(*) as cnt FROM candidates WHERE institution_id=? GROUP BY stage", (iid,)
    ).fetchall()
    cand_by_stage = {r["stage"]: r["cnt"] for r in cand_rows}

    # Interviews this month
    interviews_this_month = conn.execute(
        "SELECT COUNT(*) FROM interviews WHERE institution_id=? AND LEFT(scheduled_date,7)=to_char(NOW(),'YYYY-MM')",
        (iid,)
    ).fetchone()[0]

    # Upcoming interviews (next 7 days)
    upcoming = conn.execute(
        "SELECT COUNT(*) FROM interviews WHERE institution_id=? AND status='Scheduled' AND scheduled_date BETWEEN to_char(NOW(),'YYYY-MM-DD') AND to_char(NOW() + interval '7 days','YYYY-MM-DD')",
        (iid,)
    ).fetchone()[0]

    # Pending approvals
    pending_approvals = conn.execute(
        "SELECT COUNT(*) FROM job_requisitions WHERE institution_id=? AND status='Pending Approval'", (iid,)
    ).fetchone()[0]

    # Offers pending response
    offers_pending = conn.execute(
        "SELECT COUNT(*) FROM offers WHERE institution_id=? AND status='Sent'", (iid,)
    ).fetchone()[0]

    # Hired this month
    hired_this_month = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE institution_id=? AND stage='Hired' AND LEFT(updated_at,7)=to_char(NOW(),'YYYY-MM')",
        (iid,)
    ).fetchone()[0]

    conn.close()
    return {
        "req_by_status": req_by_status,
        "cand_by_stage": cand_by_stage,
        "interviews_this_month": interviews_this_month,
        "upcoming_interviews": upcoming,
        "pending_approvals": pending_approvals,
        "offers_pending": offers_pending,
        "hired_this_month": hired_this_month,
        "total_requisitions": sum(req_by_status.values()),
        "total_candidates": sum(cand_by_stage.values()),
    }

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

# ---------------------------------------------------------------------------
# Holiday Manager
# ---------------------------------------------------------------------------
LEAVE_MANAGE_ROLES = ("superadmin", "hr_manager", "hr_admin")

@app.get("/api/holidays")
def list_holidays(year: Optional[int] = None, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    q = "SELECT * FROM holidays WHERE institution_id=?"
    p = [inst_id]
    if year:
        q += " AND year=?"; p.append(year)
    q += " ORDER BY date"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/holidays", status_code=201)
def create_holiday(body: HolidayIn, user: dict = Depends(require_roles(*LEAVE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO holidays (institution_id,name,date,year,created_by) VALUES (?,?,?,?,?)",
            (inst_id, body.name, body.date, body.year, user["username"])
        )
        conn.commit()
    except IntegrityError as e:
        conn.rollback(); conn.close()
        raise HTTPException(400, "A holiday already exists on this date")
    row = conn.execute("SELECT * FROM holidays WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/holidays/{holiday_id}", status_code=204)
def delete_holiday(holiday_id: int, user: dict = Depends(require_roles(*LEAVE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    conn.execute("DELETE FROM holidays WHERE id=? AND institution_id=?", (holiday_id, inst_id))
    conn.commit(); conn.close()

# ---------------------------------------------------------------------------
# Leave — Types
# ---------------------------------------------------------------------------
@app.get("/api/leave/types")
def list_leave_types(user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM leave_types WHERE institution_id=? AND is_active=1 ORDER BY name", (inst_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/leave/types", status_code=201)
def create_leave_type(body: LeaveTypeIn, user: dict = Depends(require_roles(*LEAVE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    conn.execute(
        "INSERT INTO leave_types (institution_id,name,annual_entitlement,requires_approval,requires_attachment,is_paid,is_active) VALUES (?,?,?,?,?,?,?)",
        (inst_id, body.name, body.annual_entitlement, 1 if body.requires_approval else 0,
         1 if body.requires_attachment else 0, 1 if body.is_paid else 0, 1 if body.is_active else 0)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM leave_types WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)

@app.put("/api/leave/types/{type_id}")
def update_leave_type(type_id: int, body: LeaveTypeIn, user: dict = Depends(require_roles(*LEAVE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute("SELECT id FROM leave_types WHERE id=? AND institution_id=?", (type_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Leave type not found")
    conn.execute(
        "UPDATE leave_types SET name=?,annual_entitlement=?,requires_approval=?,requires_attachment=?,is_paid=?,is_active=? WHERE id=?",
        (body.name, body.annual_entitlement, 1 if body.requires_approval else 0,
         1 if body.requires_attachment else 0, 1 if body.is_paid else 0, 1 if body.is_active else 0, type_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM leave_types WHERE id=?", (type_id,)).fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/leave/types/{type_id}", status_code=204)
def delete_leave_type(type_id: int, user: dict = Depends(require_roles(*LEAVE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    conn.execute("UPDATE leave_types SET is_active=0 WHERE id=? AND institution_id=?", (type_id, inst_id))
    conn.commit(); conn.close()

# ---------------------------------------------------------------------------
# Leave — Balances
# ---------------------------------------------------------------------------
@app.get("/api/leave/balances")
def list_leave_balances(employee_id: Optional[str] = None, year: Optional[int] = None,
                        user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    year = year or datetime.now().year
    conn = get_db()
    q = """
        SELECT b.*, lt.name AS leave_type_name, e.full_name AS employee_name, e.department
        FROM leave_balances b
        JOIN leave_types lt ON lt.id = b.leave_type_id
        JOIN employees e ON e.employee_id = b.employee_id AND e.institution_id = b.institution_id
        WHERE b.institution_id=? AND b.year=?
    """
    p: list = [inst_id, year]
    if user["role"] == "employee":
        q += " AND b.employee_id=?"; p.append(user.get("employee_id", ""))
    elif user["role"] == "manager":
        frag, fp = _subordinates_in_clause(inst_id, user.get("employee_id", ""))
        q += f" AND e.employee_id IN {frag}"; p.extend(fp)
    elif employee_id:
        q += " AND b.employee_id=?"; p.append(employee_id)
    q += " ORDER BY e.full_name, lt.name"
    rows = conn.execute(q, p).fetchall()
    # Ensure every active leave type has a balance row for the employees being viewed, so
    # a type created after an employee joined still shows up with its default entitlement.
    if user["role"] in ("employee",) and user.get("employee_id"):
        types = conn.execute("SELECT id FROM leave_types WHERE institution_id=? AND is_active=1", (inst_id,)).fetchall()
        existing_type_ids = {r["leave_type_id"] for r in rows}
        missing = [t["id"] for t in types if t["id"] not in existing_type_ids]
        if missing:
            for tid in missing:
                _get_or_create_leave_balance(conn, inst_id, user["employee_id"], tid, year)
            conn.commit()
            rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.patch("/api/leave/balances/{balance_id}")
def adjust_leave_balance(balance_id: int, body: LeaveBalanceAdjustIn, user: dict = Depends(require_roles(*LEAVE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    bal = conn.execute("SELECT * FROM leave_balances WHERE id=? AND institution_id=?", (balance_id, inst_id)).fetchone()
    if not bal:
        conn.close(); raise HTTPException(404, "Balance not found")
    entitled = body.entitled_days if body.entitled_days is not None else bal["entitled_days"]
    carried = body.carried_forward_days if body.carried_forward_days is not None else bal["carried_forward_days"]
    conn.execute("UPDATE leave_balances SET entitled_days=?,carried_forward_days=? WHERE id=?", (entitled, carried, balance_id))
    conn.commit()
    row = conn.execute("SELECT * FROM leave_balances WHERE id=?", (balance_id,)).fetchone()
    conn.close()
    return dict(row)

# ---------------------------------------------------------------------------
# Leave — Applications
# ---------------------------------------------------------------------------
@app.get("/api/leave/applications")
def list_leave_applications(status: Optional[str] = None, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    q = """
        SELECT a.*, lt.name AS leave_type_name, e.full_name AS employee_name, e.department, e.designation
        FROM leave_applications a
        JOIN leave_types lt ON lt.id = a.leave_type_id
        JOIN employees e ON e.employee_id = a.employee_id AND e.institution_id = a.institution_id
        WHERE a.institution_id=?
    """
    p: list = [inst_id]
    if status: q += " AND a.status=?"; p.append(status)
    if user["role"] == "manager":
        frag, fp = _subordinates_in_clause(inst_id, user.get("employee_id", ""))
        q += f" AND e.employee_id IN {frag}"; p.extend(fp)
    elif user["role"] == "employee":
        q += " AND a.employee_id=?"; p.append(user.get("employee_id", ""))
    q += " ORDER BY a.created_at DESC"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/leave/applications", status_code=201)
def create_leave_application(body: LeaveApplicationIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    if user["role"] == "employee" and user.get("employee_id") != body.employee_id:
        conn.close(); raise HTTPException(403, "You can only apply leave for yourself")
    emp = conn.execute("SELECT * FROM employees WHERE employee_id=? AND institution_id=?",
                        (body.employee_id, inst_id)).fetchone()
    if not emp:
        conn.close(); raise HTTPException(404, "Employee not found")
    lt = conn.execute("SELECT * FROM leave_types WHERE id=? AND institution_id=? AND is_active=1",
                       (body.leave_type_id, inst_id)).fetchone()
    if not lt:
        conn.close(); raise HTTPException(404, "Leave type not found")
    if lt["requires_attachment"] and not body.attachment:
        conn.close(); raise HTTPException(400, f"'{lt['name']}' requires a supporting document to be attached")

    days = _compute_leave_days(conn, inst_id, body.start_date, body.end_date)
    if days <= 0:
        conn.close(); raise HTTPException(400, "Selected date range has no working days to apply (all weekends/public holidays)")

    year = datetime.strptime(body.start_date, "%Y-%m-%d").year
    balance = _get_or_create_leave_balance(conn, inst_id, body.employee_id, body.leave_type_id, year)
    available = balance["entitled_days"] + balance["carried_forward_days"] - balance["used_days"]
    if days > available:
        conn.close(); raise HTTPException(400, f"Insufficient balance: requesting {days} day(s), only {available} available")

    status = "Pending Approval" if lt["requires_approval"] else "Approved"
    conn.execute(
        "INSERT INTO leave_applications (institution_id,employee_id,leave_type_id,start_date,end_date,days_count,status,reason,attachment,requested_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (inst_id, body.employee_id, body.leave_type_id, body.start_date, body.end_date, days, status,
         body.reason, body.attachment, user["username"])
    )
    app_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    if status == "Approved":
        conn.execute("UPDATE leave_balances SET used_days=used_days+? WHERE id=?", (days, balance["id"]))

    _log_leave(conn, inst_id, app_id, body.employee_id, "Applied",
               f"Applied for {lt['name']}: {body.start_date} to {body.end_date} ({days} working day(s)) — status: {status}", user)
    conn.commit()
    row = conn.execute("SELECT * FROM leave_applications WHERE id=?", (app_id,)).fetchone()
    conn.close()
    return dict(row)

@app.patch("/api/leave/applications/{app_id}/status")
def update_leave_status(app_id: int, body: LeaveStatusIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    valid = ("Approved", "Rejected", "Cancelled")
    if body.status not in valid:
        raise HTTPException(400, f"status must be one of: {', '.join(valid)}")
    conn = get_db()
    application = conn.execute("SELECT * FROM leave_applications WHERE id=? AND institution_id=?", (app_id, inst_id)).fetchone()
    if not application:
        conn.close(); raise HTTPException(404, "Application not found")

    if body.status in ("Approved", "Rejected"):
        can_approve = user["role"] in ("superadmin", "hr_manager", "hr_admin", "manager")
        if not can_approve:
            conn.close(); raise HTTPException(403, "Only a manager or HR can approve/reject leave")
        if application["status"] != "Pending Approval":
            conn.close(); raise HTTPException(400, f"Application is already {application['status']}")
        if body.status == "Approved":
            year = datetime.strptime(application["start_date"], "%Y-%m-%d").year
            balance = _get_or_create_leave_balance(conn, inst_id, application["employee_id"], application["leave_type_id"], year)
            conn.execute("UPDATE leave_balances SET used_days=used_days+? WHERE id=?", (application["days_count"], balance["id"]))
        conn.execute("UPDATE leave_applications SET status=?,approved_by=?,notes=? WHERE id=?",
                     (body.status, user["username"], body.notes, app_id))
    elif body.status == "Cancelled":
        if user["role"] == "employee" and user.get("employee_id") != application["employee_id"]:
            conn.close(); raise HTTPException(403, "Access denied")
        if application["status"] not in ("Pending Approval", "Approved"):
            conn.close(); raise HTTPException(400, f"Application is already {application['status']}")
        if application["status"] == "Approved":
            year = datetime.strptime(application["start_date"], "%Y-%m-%d").year
            balance = _get_or_create_leave_balance(conn, inst_id, application["employee_id"], application["leave_type_id"], year)
            conn.execute("UPDATE leave_balances SET used_days=used_days-? WHERE id=?", (application["days_count"], balance["id"]))
        conn.execute("UPDATE leave_applications SET status='Cancelled',notes=? WHERE id=?", (body.notes, app_id))

    _log_leave(conn, inst_id, app_id, application["employee_id"], f"Status changed to {body.status}",
               body.notes or "", user)
    conn.commit()
    row = conn.execute("SELECT * FROM leave_applications WHERE id=?", (app_id,)).fetchone()
    conn.close()
    return dict(row)

@app.get("/api/employees/{employee_id}/leave-history")
def get_employee_leave_history(employee_id: str, user: dict = Depends(require_roles(*LEAVE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM leave_audit_log WHERE employee_id=? AND institution_id=? ORDER BY created_at ASC",
        (employee_id, inst_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ---------------------------------------------------------------------------
# Projects (managed by HR Manager) — feeds Timesheet's project selector
# ---------------------------------------------------------------------------
PROJECT_MANAGE_ROLES = ("superadmin", "hr_manager")

@app.get("/api/projects")
def list_projects(status: Optional[str] = None, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    q = """
        SELECT p.*,
            (SELECT COUNT(DISTINCT ta.employee_id) FROM task_assignments ta
                JOIN project_tasks t2 ON t2.id=ta.task_id WHERE t2.project_id=p.id) AS member_count,
            (SELECT COUNT(*) FROM project_tasks t WHERE t.project_id=p.id) AS task_count,
            (SELECT COALESCE(SUM(t.estimated_hours),0) FROM project_tasks t WHERE t.project_id=p.id) AS total_allocated_hours,
            (SELECT COALESCE(SUM(te.hours),0) FROM timesheet_entries te WHERE te.project_id=p.id) AS total_logged_hours
        FROM projects p
        WHERE p.institution_id=?
    """
    params: list = [inst_id]
    if status: q += " AND p.status=?"; params.append(status)
    q += " GROUP BY p.id ORDER BY p.created_at DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/projects/utilization")
def get_project_utilization(user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    """Hours clocked by project, broken down by task, for all Active projects."""
    inst_id = need_inst(user)
    conn = get_db()
    projects = conn.execute(
        "SELECT * FROM projects WHERE institution_id=? AND status='Active' ORDER BY name", (inst_id,)
    ).fetchall()
    result = []
    for p in projects:
        tasks = conn.execute("""
            SELECT t.id, t.name, t.estimated_hours, t.status,
                   COALESCE(SUM(te.hours),0) AS logged_hours
            FROM project_tasks t
            LEFT JOIN timesheet_entries te ON te.task_id = t.id
            WHERE t.project_id=? AND t.institution_id=?
            GROUP BY t.id ORDER BY t.start_date NULLS LAST, t.created_at
        """, (p["id"], inst_id)).fetchall()
        task_list = [dict(t) for t in tasks]
        project_total = sum(t["logged_hours"] for t in task_list)
        result.append({
            "id": p["id"], "name": p["name"], "status": p["status"],
            "total_hours": project_total, "tasks": task_list,
        })
    conn.close()
    return result

@app.get("/api/projects/mine")
def list_my_projects(user: dict = Depends(get_current_user)):
    """Projects the current employee can log time against — used to populate the timesheet project selector."""
    inst_id = need_inst(user)
    if not user.get("employee_id"):
        return []
    conn = get_db()
    rows = conn.execute("""
        SELECT DISTINCT p.* FROM projects p
        WHERE p.institution_id=? AND p.status='Active' AND (
            EXISTS (
                SELECT 1 FROM task_assignments ta JOIN project_tasks t ON t.id=ta.task_id
                WHERE t.project_id=p.id AND ta.employee_id=?
            )
            OR EXISTS (SELECT 1 FROM project_tasks t WHERE t.project_id=p.id AND t.open_to_all=1)
        )
        ORDER BY p.name
    """, (inst_id, user["employee_id"])).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/projects", status_code=201)
def create_project(body: ProjectIn, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    conn.execute(
        "INSERT INTO projects (institution_id,name,description,status,created_by) VALUES (?,?,?,?,?)",
        (inst_id, body.name, body.description, body.status, user["username"])
    )
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)

@app.put("/api/projects/{project_id}")
def update_project(project_id: int, body: ProjectIn, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute("SELECT id FROM projects WHERE id=? AND institution_id=?", (project_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Project not found")
    conn.execute(
        "UPDATE projects SET name=?,description=?,status=? WHERE id=?",
        (body.name, body.description, body.status, project_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: int, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    if conn.execute("SELECT id FROM timesheet_entries WHERE project_id=? AND institution_id=?", (project_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(400, "Cannot delete a project that already has logged timesheet hours — set it to Completed instead")
    conn.execute("DELETE FROM projects WHERE id=? AND institution_id=?", (project_id, inst_id))
    conn.commit(); conn.close()

# ---------------------------------------------------------------------------
# Project Tasks (managed by HR Manager)
# ---------------------------------------------------------------------------
@app.get("/api/projects/{project_id}/tasks")
def list_project_tasks(project_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute("SELECT id FROM projects WHERE id=? AND institution_id=?", (project_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Project not found")
    # Project managers and anyone already assigned to a task in this project see every
    # task. An employee with no assignment here only sees tasks marked "ALL"
    # (open_to_all) — those are the only ones they're allowed to clock hours against,
    # so anything else is irrelevant to them.
    is_assigned = bool(user.get("employee_id")) and conn.execute("""
        SELECT ta.id FROM task_assignments ta JOIN project_tasks t ON t.id=ta.task_id
        WHERE t.project_id=? AND ta.employee_id=? AND ta.institution_id=?
    """, (project_id, user.get("employee_id"), inst_id)).fetchone()
    restrict_to_open = user["role"] not in PROJECT_MANAGE_ROLES and not is_assigned
    sql = """
        SELECT t.*, COALESCE(SUM(te.hours),0) AS logged_hours
        FROM project_tasks t
        LEFT JOIN timesheet_entries te ON te.task_id = t.id
        WHERE t.project_id=? AND t.institution_id=?
    """
    if restrict_to_open:
        sql += " AND t.open_to_all=1"
    sql += " GROUP BY t.id ORDER BY t.start_date NULLS LAST, t.created_at"
    rows = conn.execute(sql, (project_id, inst_id)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/projects/{project_id}/tasks", status_code=201)
def create_project_task(project_id: int, body: ProjectTaskIn, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute("SELECT id FROM projects WHERE id=? AND institution_id=?", (project_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Project not found")
    if body.start_date and body.end_date and body.end_date < body.start_date:
        conn.close(); raise HTTPException(400, "End date must be on or after start date")
    conn.execute(
        "INSERT INTO project_tasks (institution_id,project_id,name,description,estimated_hours,start_date,end_date,status,created_by) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (inst_id, project_id, body.name, body.description, body.estimated_hours,
         body.start_date, body.end_date, body.status, user["username"])
    )
    conn.commit()
    row = conn.execute("SELECT * FROM project_tasks WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)

@app.put("/api/projects/{project_id}/tasks/{task_id}")
def update_project_task(project_id: int, task_id: int, body: ProjectTaskIn, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute("SELECT id FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?", (task_id, project_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Task not found")
    if body.start_date and body.end_date and body.end_date < body.start_date:
        conn.close(); raise HTTPException(400, "End date must be on or after start date")
    conn.execute(
        "UPDATE project_tasks SET name=?,description=?,estimated_hours=?,start_date=?,end_date=?,status=? WHERE id=?",
        (body.name, body.description, body.estimated_hours, body.start_date, body.end_date, body.status, task_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM project_tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/projects/{project_id}/tasks/{task_id}", status_code=204)
def delete_project_task(project_id: int, task_id: int, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    if conn.execute("SELECT id FROM timesheet_entries WHERE task_id=? AND institution_id=?", (task_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(400, "Cannot delete a task that already has logged timesheet hours — mark it Completed instead")
    conn.execute("DELETE FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?", (task_id, project_id, inst_id))
    conn.execute("DELETE FROM task_assignments WHERE task_id=? AND institution_id=?", (task_id, inst_id))
    conn.commit(); conn.close()

# ---------------------------------------------------------------------------
# Task Assignments — per-team-member expected effort (start datetime + duration)
# on a task. Purely for capturing expected effort; actual timesheet hours
# logged against the task are NOT capped by this (see add_timesheet_entry).
# ---------------------------------------------------------------------------
@app.get("/api/projects/{project_id}/tasks/{task_id}/assignments")
def list_task_assignments(project_id: int, task_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute("SELECT id FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?", (task_id, project_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Task not found")
    rows = conn.execute("""
        SELECT ta.*, e.full_name, e.department, e.designation
        FROM task_assignments ta
        JOIN employees e ON e.employee_id = ta.employee_id AND e.institution_id = ta.institution_id
        WHERE ta.task_id=? AND ta.institution_id=?
        ORDER BY ta.start_datetime
    """, (task_id, inst_id)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/projects/{project_id}/tasks/{task_id}/assignments", status_code=201)
def add_task_assignment(project_id: int, task_id: int, body: TaskAssignmentIn, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute("SELECT id FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?", (task_id, project_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Task not found")
    if not conn.execute("SELECT id FROM employees WHERE employee_id=? AND institution_id=?", (body.employee_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Employee not found")
    if body.duration_hours <= 0:
        conn.close(); raise HTTPException(400, "Duration must be greater than 0")
    try:
        conn.execute(
            "INSERT INTO task_assignments (institution_id,task_id,employee_id,start_datetime,duration_hours,assigned_by) VALUES (?,?,?,?,?,?)",
            (inst_id, task_id, body.employee_id, body.start_datetime, body.duration_hours, user["username"])
        )
        conn.commit()
    except IntegrityError:
        conn.rollback(); conn.close()
        raise HTTPException(400, "Employee is already assigned to this task")
    row = conn.execute("SELECT * FROM task_assignments WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/projects/{project_id}/tasks/{task_id}/assignments/{employee_id}", status_code=204)
def remove_task_assignment(project_id: int, task_id: int, employee_id: str, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    conn.execute(
        "DELETE FROM task_assignments WHERE task_id=? AND employee_id=? AND institution_id=?",
        (task_id, employee_id, inst_id)
    )
    conn.commit(); conn.close()

@app.patch("/api/projects/{project_id}/tasks/{task_id}/open-to-all")
def set_task_open_to_all(project_id: int, task_id: int, body: TaskOpenToAllIn, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    """Marking a task 'ALL' lets every employee in the institution clock hours to it,
    bypassing the usual project-membership requirement (see add_timesheet_entry)."""
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute("SELECT id FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?", (task_id, project_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Task not found")
    conn.execute("UPDATE project_tasks SET open_to_all=? WHERE id=?", (1 if body.open_to_all else 0, task_id))
    conn.commit()
    row = conn.execute("SELECT * FROM project_tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return dict(row)

# ---------------------------------------------------------------------------
# Institution Notifications — configured by HR Manager/HR Admin, shown as a
# dashboard banner to all non-superadmin roles while within [start_time, end_time].
# Overlapping active windows are rejected at save time so at most one
# notification is ever active for an institution at a given moment.
# ---------------------------------------------------------------------------
NOTIFICATION_MANAGE_ROLES = ("hr_manager", "hr_admin")

def _notification_overlaps(conn, inst_id, start_time, end_time, exclude_id=None):
    q = """
        SELECT id FROM institution_notifications
        WHERE institution_id=? AND NOT (end_time <= ? OR start_time >= ?)
    """
    params: list = [inst_id, start_time, end_time]
    if exclude_id is not None:
        q += " AND id != ?"; params.append(exclude_id)
    return conn.execute(q, params).fetchone() is not None

@app.get("/api/notifications")
def list_notifications(user: dict = Depends(require_roles(*NOTIFICATION_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM institution_notifications WHERE institution_id=? ORDER BY start_time DESC", (inst_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/notifications/active")
def get_active_notification(user: dict = Depends(get_current_user)):
    inst_id = user.get("active_institution_id")
    if not inst_id or user["role"] == "superadmin":
        return None
    conn = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    row = conn.execute(
        "SELECT * FROM institution_notifications WHERE institution_id=? AND start_time<=? AND end_time>=? "
        "ORDER BY start_time DESC LIMIT 1",
        (inst_id, now, now)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

@app.post("/api/notifications", status_code=201)
def create_notification(body: NotificationIn, user: dict = Depends(require_roles(*NOTIFICATION_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    if body.end_time <= body.start_time:
        conn.close(); raise HTTPException(400, "End time must be after start time")
    if _notification_overlaps(conn, inst_id, body.start_time, body.end_time):
        conn.close(); raise HTTPException(400, "Another notification is already active/scheduled during this window")
    conn.execute(
        "INSERT INTO institution_notifications (institution_id,message,start_time,end_time,created_by) VALUES (?,?,?,?,?)",
        (inst_id, body.message, body.start_time, body.end_time, user["username"])
    )
    conn.commit()
    row = conn.execute("SELECT * FROM institution_notifications WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)

@app.put("/api/notifications/{notification_id}")
def update_notification(notification_id: int, body: NotificationIn, user: dict = Depends(require_roles(*NOTIFICATION_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute("SELECT id FROM institution_notifications WHERE id=? AND institution_id=?", (notification_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Notification not found")
    if body.end_time <= body.start_time:
        conn.close(); raise HTTPException(400, "End time must be after start time")
    if _notification_overlaps(conn, inst_id, body.start_time, body.end_time, exclude_id=notification_id):
        conn.close(); raise HTTPException(400, "Another notification is already active/scheduled during this window")
    conn.execute(
        "UPDATE institution_notifications SET message=?,start_time=?,end_time=? WHERE id=?",
        (body.message, body.start_time, body.end_time, notification_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM institution_notifications WHERE id=?", (notification_id,)).fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/notifications/{notification_id}", status_code=204)
def delete_notification(notification_id: int, user: dict = Depends(require_roles(*NOTIFICATION_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    conn.execute("DELETE FROM institution_notifications WHERE id=? AND institution_id=?", (notification_id, inst_id))
    conn.commit(); conn.close()

# ---------------------------------------------------------------------------
# System-Wide Notifications — configured by superadmin only, shown as a red
# "urgency" banner above the institution notification banner, to ALL users
# across ALL institutions (including superadmin), e.g. system downtime.
# ---------------------------------------------------------------------------
def _system_notification_overlaps(conn, start_time, end_time, exclude_id=None):
    q = "SELECT id FROM system_notifications WHERE NOT (end_time <= ? OR start_time >= ?)"
    params: list = [start_time, end_time]
    if exclude_id is not None:
        q += " AND id != ?"; params.append(exclude_id)
    return conn.execute(q, params).fetchone() is not None

@app.get("/api/system-notifications")
def list_system_notifications(user: dict = Depends(require_roles("superadmin"))):
    conn = get_db()
    rows = conn.execute("SELECT * FROM system_notifications ORDER BY start_time DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/system-notifications/active")
def get_active_system_notification(user: dict = Depends(get_current_user)):
    conn = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    row = conn.execute(
        "SELECT * FROM system_notifications WHERE start_time<=? AND end_time>=? ORDER BY start_time DESC LIMIT 1",
        (now, now)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

@app.post("/api/system-notifications", status_code=201)
def create_system_notification(body: NotificationIn, user: dict = Depends(require_roles("superadmin"))):
    conn = get_db()
    if body.end_time <= body.start_time:
        conn.close(); raise HTTPException(400, "End time must be after start time")
    if _system_notification_overlaps(conn, body.start_time, body.end_time):
        conn.close(); raise HTTPException(400, "Another system notification is already active/scheduled during this window")
    conn.execute(
        "INSERT INTO system_notifications (message,start_time,end_time,created_by) VALUES (?,?,?,?)",
        (body.message, body.start_time, body.end_time, user["username"])
    )
    conn.commit()
    row = conn.execute("SELECT * FROM system_notifications WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)

@app.put("/api/system-notifications/{notification_id}")
def update_system_notification(notification_id: int, body: NotificationIn, user: dict = Depends(require_roles("superadmin"))):
    conn = get_db()
    if not conn.execute("SELECT id FROM system_notifications WHERE id=?", (notification_id,)).fetchone():
        conn.close(); raise HTTPException(404, "Notification not found")
    if body.end_time <= body.start_time:
        conn.close(); raise HTTPException(400, "End time must be after start time")
    if _system_notification_overlaps(conn, body.start_time, body.end_time, exclude_id=notification_id):
        conn.close(); raise HTTPException(400, "Another system notification is already active/scheduled during this window")
    conn.execute(
        "UPDATE system_notifications SET message=?,start_time=?,end_time=? WHERE id=?",
        (body.message, body.start_time, body.end_time, notification_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM system_notifications WHERE id=?", (notification_id,)).fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/system-notifications/{notification_id}", status_code=204)
def delete_system_notification(notification_id: int, user: dict = Depends(require_roles("superadmin"))):
    conn = get_db()
    conn.execute("DELETE FROM system_notifications WHERE id=?", (notification_id,))
    conn.commit(); conn.close()

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

# ---------------------------------------------------------------------------
# Timesheets
# ---------------------------------------------------------------------------
@app.get("/api/timesheets")
def list_timesheets(status: Optional[str] = None, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    q = """
        SELECT t.*, e.full_name AS employee_name, e.department, e.designation,
               COALESCE(SUM(te.hours),0) AS total_hours
        FROM timesheets t
        JOIN employees e ON e.employee_id = t.employee_id AND e.institution_id = t.institution_id
        LEFT JOIN timesheet_entries te ON te.timesheet_id = t.id
        WHERE t.institution_id=?
    """
    params: list = [inst_id]
    if status: q += " AND t.status=?"; params.append(status)
    if user["role"] == "manager":
        frag, fp = _subordinates_in_clause(inst_id, user.get("employee_id", ""))
        q += f" AND e.employee_id IN {frag}"; params.extend(fp)
    elif user["role"] == "employee":
        q += " AND t.employee_id=?"; params.append(user.get("employee_id", ""))
    q += " GROUP BY t.id, e.full_name, e.department, e.designation ORDER BY t.period_start DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/timesheets", status_code=201)
def start_timesheet(body: TimesheetStartIn, user: dict = Depends(get_current_user)):
    """Get-or-create the Draft timesheet for an employee's period (idempotent)."""
    inst_id = need_inst(user)
    if user["role"] == "employee" and user.get("employee_id") != body.employee_id:
        raise HTTPException(403, "You can only manage your own timesheet")
    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM timesheets WHERE employee_id=? AND period_start=? AND period_end=? AND institution_id=?",
        (body.employee_id, body.period_start, body.period_end, inst_id)
    ).fetchone()
    if existing:
        conn.close()
        return dict(existing)
    conn.execute(
        "INSERT INTO timesheets (institution_id,employee_id,period_start,period_end) VALUES (?,?,?,?)",
        (inst_id, body.employee_id, body.period_start, body.period_end)
    )
    ts_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    _log_timesheet(conn, inst_id, ts_id, body.employee_id, "Created",
                    f"Timesheet created for {body.period_start} to {body.period_end}", user)
    conn.commit()
    row = conn.execute("SELECT * FROM timesheets WHERE id=?", (ts_id,)).fetchone()
    conn.close()
    return dict(row)

@app.get("/api/timesheets/{ts_id}")
def get_timesheet(ts_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    ts = conn.execute("SELECT * FROM timesheets WHERE id=? AND institution_id=?", (ts_id, inst_id)).fetchone()
    if not ts:
        conn.close(); raise HTTPException(404, "Timesheet not found")
    if user["role"] == "employee" and user.get("employee_id") != ts["employee_id"]:
        conn.close(); raise HTTPException(403, "Access denied")
    entries = conn.execute("""
        SELECT te.*, p.name AS project_name, t.name AS task_name
        FROM timesheet_entries te
        JOIN projects p ON p.id = te.project_id
        LEFT JOIN project_tasks t ON t.id = te.task_id
        WHERE te.timesheet_id=? ORDER BY te.date, p.name
    """, (ts_id,)).fetchall()
    conn.close()
    result = dict(ts)
    result["entries"] = [dict(e) for e in entries]
    result["total_hours"] = sum(e["hours"] for e in result["entries"])
    return result

@app.post("/api/timesheets/{ts_id}/entries", status_code=201)
def add_timesheet_entry(ts_id: int, body: TimesheetEntryIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    ts = conn.execute("SELECT * FROM timesheets WHERE id=? AND institution_id=?", (ts_id, inst_id)).fetchone()
    if not ts:
        conn.close(); raise HTTPException(404, "Timesheet not found")
    if user["role"] == "employee" and user.get("employee_id") != ts["employee_id"]:
        conn.close(); raise HTTPException(403, "Access denied")
    if ts["status"] != "Draft":
        conn.close(); raise HTTPException(400, f"Cannot edit a {ts['status']} timesheet")
    task = conn.execute(
        "SELECT id, open_to_all FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?",
        (body.task_id, body.project_id, inst_id)
    ).fetchone()
    if not task:
        conn.close(); raise HTTPException(400, "Selected task does not belong to this project")
    if not task["open_to_all"] and not conn.execute(
        "SELECT id FROM task_assignments WHERE task_id=? AND employee_id=? AND institution_id=?",
        (body.task_id, ts["employee_id"], inst_id)
    ).fetchone():
        conn.close(); raise HTTPException(403, "This employee is not assigned to the selected task")
    if body.hours <= 0 or body.hours > 24:
        conn.close(); raise HTTPException(400, "Hours must be between 0 and 24")
    if not (ts["period_start"] <= body.date <= ts["period_end"]):
        conn.close(); raise HTTPException(400, "Entry date must fall within the timesheet's period")

    conn.execute(
        "INSERT INTO timesheet_entries (institution_id,timesheet_id,project_id,task_id,date,hours,description) VALUES (?,?,?,?,?,?,?)",
        (inst_id, ts_id, body.project_id, body.task_id, body.date, body.hours, body.description)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM timesheet_entries WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/timesheets/{ts_id}/entries/{entry_id}", status_code=204)
def delete_timesheet_entry(ts_id: int, entry_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    ts = conn.execute("SELECT * FROM timesheets WHERE id=? AND institution_id=?", (ts_id, inst_id)).fetchone()
    if not ts:
        conn.close(); raise HTTPException(404, "Timesheet not found")
    if user["role"] == "employee" and user.get("employee_id") != ts["employee_id"]:
        conn.close(); raise HTTPException(403, "Access denied")
    if ts["status"] != "Draft":
        conn.close(); raise HTTPException(400, f"Cannot edit a {ts['status']} timesheet")
    conn.execute("DELETE FROM timesheet_entries WHERE id=? AND timesheet_id=?", (entry_id, ts_id))
    conn.commit(); conn.close()

@app.patch("/api/timesheets/{ts_id}/status")
def update_timesheet_status(ts_id: int, body: TimesheetStatusIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    valid = ("Submitted", "Approved", "Rejected")
    if body.status not in valid:
        raise HTTPException(400, f"status must be one of: {', '.join(valid)}")
    conn = get_db()
    ts = conn.execute("SELECT * FROM timesheets WHERE id=? AND institution_id=?", (ts_id, inst_id)).fetchone()
    if not ts:
        conn.close(); raise HTTPException(404, "Timesheet not found")

    if body.status == "Submitted":
        if user["role"] == "employee" and user.get("employee_id") != ts["employee_id"]:
            conn.close(); raise HTTPException(403, "Access denied")
        if ts["status"] != "Draft":
            conn.close(); raise HTTPException(400, f"Only a Draft timesheet can be submitted (current status: {ts['status']})")
        entry_count = conn.execute("SELECT COUNT(*) FROM timesheet_entries WHERE timesheet_id=?", (ts_id,)).fetchone()[0]
        if entry_count == 0:
            conn.close(); raise HTTPException(400, "Cannot submit an empty timesheet")
        conn.execute(
            "UPDATE timesheets SET status='Submitted',submitted_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=?",
            (ts_id,)
        )
    else:  # Approved | Rejected
        can_approve = user["role"] in ("superadmin", "hr_manager", "hr_admin", "manager")
        if not can_approve:
            conn.close(); raise HTTPException(403, "Only a manager or HR can approve/reject timesheets")
        if ts["status"] != "Submitted":
            conn.close(); raise HTTPException(400, f"Only a Submitted timesheet can be reviewed (current status: {ts['status']})")
        conn.execute("UPDATE timesheets SET status=?,approved_by=?,notes=? WHERE id=?",
                     (body.status, user["username"], body.notes, ts_id))

    _log_timesheet(conn, inst_id, ts_id, ts["employee_id"], f"Status changed to {body.status}", body.notes or "", user)
    conn.commit()
    row = conn.execute("SELECT * FROM timesheets WHERE id=?", (ts_id,)).fetchone()
    conn.close()
    return dict(row)

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
