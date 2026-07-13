import fcntl
import os
import logging
import tempfile
import time

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response

try:
    from db import get_db
except ImportError:
    from ems.db import get_db

# payroll_calc import moved to routers/payroll.py (only used there now).

try:
    from core.deps import hash_password, verify_password
    from core.onboarding_seed import seed_ob_templates
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
    from routers.employees import router as employees_router
    from routers.auth import router as auth_router
    from routers.meta import router as meta_router
    from routers.frontend import router as frontend_router, STATIC_DIR
except ImportError:
    from ems.core.deps import hash_password, verify_password
    from ems.core.onboarding_seed import seed_ob_templates
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
app.include_router(employees_router)
app.include_router(auth_router)
app.include_router(meta_router)

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
    # Serializes this function's DDL across concurrent same-host processes
    # that import main.py at the same time (e.g. parallel pytest-xdist
    # workers) — without this, two processes running the same CREATE OR
    # REPLACE FUNCTION / ALTER TABLE statements concurrently can hit
    # Postgres's "tuple concurrently updated" error on the system catalog.
    # A plain filesystem lock (not a Postgres advisory lock) is used
    # deliberately: an advisory lock's blocking wait is itself a SQL
    # statement, and if the winning process's DDL run takes longer than
    # Supabase's statement_timeout, every OTHER waiting process gets its
    # wait cancelled with "canceling statement due to statement timeout" —
    # which then fails that process's app import entirely. A file lock has
    # no such interaction with the DB and is sufficient since every worker
    # racing on this runs on the same machine.
    lock_path = os.path.join(tempfile.gettempdir(), "ems_init_db.lock")
    with open(lock_path, "w") as lockfile:
        fcntl.flock(lockfile, fcntl.LOCK_EX)
        try:
            conn = get_db()
            try:
                _init_db_body(conn)
            finally:
                conn.close()
        finally:
            fcntl.flock(lockfile, fcntl.LOCK_UN)


def _init_db_body(conn):
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
            must_change_password INTEGER NOT NULL DEFAULT 0,
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
    conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password INTEGER NOT NULL DEFAULT 0")
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
    # column already NUMERIC(12,2) is a no-op in terms of data, BUT an
    # unconditional ALTER TABLE ... ALTER COLUMN still takes an
    # AccessExclusiveLock on the table every single time regardless of
    # whether anything actually changes — on every app boot, forever. Under
    # concurrent load (e.g. two app/test processes starting up close
    # together) that unconditional exclusive lock is what produced a real
    # Postgres deadlock against ordinary traffic on these same tables.
    # Checking information_schema first turns an already-migrated column
    # into a plain SELECT with no lock escalation at all.
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
        already_numeric = conn.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name=? AND column_name=?
              AND data_type='numeric' AND numeric_precision=12 AND numeric_scale=2
        """, (_tbl, _col)).fetchone()
        if not already_numeric:
            conn.execute(f"ALTER TABLE {_tbl} ALTER COLUMN {_col} TYPE NUMERIC(12,2) USING {_col}::numeric(12,2)")
    conn.commit()

    # Enable RLS on every table so Supabase's auto-exposed PostgREST/GraphQL API
    # can't read/write this data. Our app connects as the table owner (postgres),
    # which bypasses RLS by default — access control stays enforced in the API layer.
    # Same AccessExclusiveLock-every-boot concern as the NUMERIC migration
    # above: check pg_class.relrowsecurity first so an already-enabled table
    # is a no-op SELECT instead of a repeated exclusive-lock DDL statement.
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
        rls_enabled = conn.execute(
            "SELECT relrowsecurity FROM pg_class WHERE relnamespace='public'::regnamespace AND relname=?",
            (tbl,)
        ).fetchone()
        if not (rls_enabled and rls_enabled[0]):
            conn.execute(f"ALTER TABLE public.{tbl} ENABLE ROW LEVEL SECURITY")
    conn.commit()

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

init_db()

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
