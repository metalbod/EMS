"""20260717_0001: Full schema DDL (moved from main.py init_db)

Revision ID: 20260717_0001
Revises: 75b14e73962f
Create Date: 2026-07-17 10:00:00.000000

This migration contains all the schema DDL statements that were previously
defined in main.py's _init_db_body() function — all CREATE TABLE, CREATE
FUNCTION, CREATE TRIGGER, ALTER TABLE, and RLS ENABLE statements.

Going forward, new schema changes should be written as separate Alembic
migrations rather than added to main.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260717_0001'
down_revision: Union[str, Sequence[str], None] = '75b14e73962f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the set_updated_at() trigger function
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # institutions table
    op.execute("""
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
        )
    """)

    # users table
    op.execute("""
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
        )
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_users_upd ON users")
    op.execute("""
        CREATE TRIGGER trg_users_upd BEFORE UPDATE ON users
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    # employees table
    op.execute("""
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
        )
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_employees_upd ON employees")
    op.execute("""
        CREATE TRIGGER trg_employees_upd BEFORE UPDATE ON employees
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    # audit_logs table
    op.execute("""
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
        )
    """)

    # job_requisitions table
    op.execute("""
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
        )
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_req_upd ON job_requisitions")
    op.execute("""
        CREATE TRIGGER trg_req_upd BEFORE UPDATE ON job_requisitions
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    # candidates table
    op.execute("""
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
        )
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_cand_upd ON candidates")
    op.execute("""
        CREATE TRIGGER trg_cand_upd BEFORE UPDATE ON candidates
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    # interviews table
    op.execute("""
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
        )
    """)

    # interview_scores table
    op.execute("""
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
        )
    """)

    # offers table
    op.execute("""
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
        )
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_offer_upd ON offers")
    op.execute("""
        CREATE TRIGGER trg_offer_upd BEFORE UPDATE ON offers
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    # candidate_audit_log table
    op.execute("""
        CREATE TABLE IF NOT EXISTS candidate_audit_log (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            candidate_id    INTEGER NOT NULL REFERENCES candidates(id),
            action          TEXT    NOT NULL,
            detail          TEXT,
            performed_by    TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)

    # ob_audit_log table
    op.execute("""
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
        )
    """)

    # hr_notes table
    op.execute("""
        CREATE TABLE IF NOT EXISTS hr_notes (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            employee_id     TEXT    NOT NULL,
            note_type       TEXT    NOT NULL DEFAULT 'general',
            body            TEXT    NOT NULL,
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            deleted         INTEGER NOT NULL DEFAULT 0
        )
    """)

    # ob_templates table
    op.execute("""
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
        )
    """)

    # ob_checklists table
    op.execute("""
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
        )
    """)

    # ob_checklist_items table
    op.execute("""
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
        )
    """)

    # ld_courses table
    op.execute("""
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
        )
    """)

    # ld_enrollments table
    op.execute("""
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
        )
    """)

    # ld_audit_log table
    op.execute("""
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
        )
    """)

    # ld_quizzes table
    op.execute("""
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
        )
    """)

    # ld_quiz_questions table
    op.execute("""
        CREATE TABLE IF NOT EXISTS ld_quiz_questions (
            id              SERIAL  PRIMARY KEY,
            quiz_id         INTEGER NOT NULL REFERENCES ld_quizzes(id),
            institution_id  INTEGER NOT NULL,
            question_text   TEXT    NOT NULL,
            question_type   TEXT    NOT NULL DEFAULT 'single',
            options         JSONB   NOT NULL,
            order_index     INTEGER NOT NULL DEFAULT 0
        )
    """)

    # ld_quiz_attempts table
    op.execute("""
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
        )
    """)

    # ld_course_modules table
    op.execute("""
        CREATE TABLE IF NOT EXISTS ld_course_modules (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            course_id       INTEGER NOT NULL REFERENCES ld_courses(id),
            title           TEXT    NOT NULL,
            content_type    TEXT    NOT NULL DEFAULT 'text',
            content         TEXT,
            order_index     INTEGER NOT NULL DEFAULT 0
        )
    """)

    # ld_lesson_progress table
    op.execute("""
        CREATE TABLE IF NOT EXISTS ld_lesson_progress (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            enrollment_id   INTEGER NOT NULL REFERENCES ld_enrollments(id),
            module_id       INTEGER NOT NULL REFERENCES ld_course_modules(id),
            employee_id     TEXT    NOT NULL,
            viewed_at       TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(enrollment_id, module_id)
        )
    """)

    # holidays table
    op.execute("""
        CREATE TABLE IF NOT EXISTS holidays (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            name            TEXT    NOT NULL,
            date            TEXT    NOT NULL,
            year            INTEGER NOT NULL,
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(institution_id, date)
        )
    """)

    # leave_types table
    op.execute("""
        CREATE TABLE IF NOT EXISTS leave_types (
            id                  SERIAL  PRIMARY KEY,
            institution_id      INTEGER NOT NULL REFERENCES institutions(id),
            name                TEXT    NOT NULL,
            annual_entitlement  REAL    NOT NULL DEFAULT 14,
            requires_approval   INTEGER NOT NULL DEFAULT 1,
            requires_attachment INTEGER NOT NULL DEFAULT 0,
            is_active           INTEGER NOT NULL DEFAULT 1,
            created_at          TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)

    # leave_balances table
    op.execute("""
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
        )
    """)

    # leave_applications table
    op.execute("""
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
        )
    """)

    # leave_audit_log table
    op.execute("""
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
        )
    """)

    # projects table
    op.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            name            TEXT    NOT NULL,
            description     TEXT,
            status          TEXT    NOT NULL DEFAULT 'Active',
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)

    # project_tasks table
    op.execute("""
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

    # timesheets table
    op.execute("""
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
        )
    """)

    # timesheet_entries table
    op.execute("""
        CREATE TABLE IF NOT EXISTS timesheet_entries (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            timesheet_id    INTEGER NOT NULL REFERENCES timesheets(id),
            project_id      INTEGER NOT NULL REFERENCES projects(id),
            task_id         INTEGER REFERENCES project_tasks(id),
            date            TEXT    NOT NULL,
            hours           REAL    NOT NULL,
            description     TEXT
        )
    """)

    # timesheet_audit_log table
    op.execute("""
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
        )
    """)

    # Idempotent column additions
    op.execute("ALTER TABLE ob_templates ADD COLUMN IF NOT EXISTS linked_ld_course_id INTEGER")
    op.execute("ALTER TABLE ob_checklist_items ADD COLUMN IF NOT EXISTS linked_ld_course_id INTEGER")
    op.execute("ALTER TABLE ob_checklist_items ADD COLUMN IF NOT EXISTS linked_ld_enrollment_id INTEGER")
    op.execute("ALTER TABLE ld_quizzes ADD COLUMN IF NOT EXISTS randomize_questions INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE ld_quizzes ADD COLUMN IF NOT EXISTS randomize_options INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE ld_quiz_questions ADD COLUMN IF NOT EXISTS question_type TEXT NOT NULL DEFAULT 'single'")
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS logo_url TEXT")

    # task_assignments table
    op.execute("""
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

    # Drop obsolete project_members table if it exists
    op.execute("DROP TABLE IF EXISTS project_members")

    # Add task_id to timesheet_entries
    op.execute("ALTER TABLE timesheet_entries ADD COLUMN IF NOT EXISTS task_id INTEGER REFERENCES project_tasks(id)")

    # Add open_to_all to project_tasks
    op.execute("ALTER TABLE project_tasks ADD COLUMN IF NOT EXISTS open_to_all INTEGER NOT NULL DEFAULT 0")

    # institution_notifications table
    op.execute("""
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

    # system_notifications table (global/unscoped, RLS deliberately disabled on this one)
    op.execute("""
        CREATE TABLE IF NOT EXISTS system_notifications (
            id              SERIAL  PRIMARY KEY,
            message         TEXT    NOT NULL,
            start_time      TEXT    NOT NULL,
            end_time        TEXT    NOT NULL,
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)

    # payroll_runs table
    op.execute("""
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

    # payslips table
    op.execute("""
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

    # Additional institution columns
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS pay_cycle TEXT NOT NULL DEFAULT 'Monthly'")
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS pay_day INTEGER NOT NULL DEFAULT 25")

    # Additional user columns
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password INTEGER NOT NULL DEFAULT 0")

    # Additional leave_types columns
    op.execute("ALTER TABLE leave_types ADD COLUMN IF NOT EXISTS is_paid INTEGER NOT NULL DEFAULT 1")

    # Additional employee columns
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS num_children INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS salary_type TEXT NOT NULL DEFAULT 'Monthly'")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS hourly_rate NUMERIC(12,2) NOT NULL DEFAULT 0")

    # Additional payslips columns
    op.execute("ALTER TABLE payslips ADD COLUMN IF NOT EXISTS salary_type TEXT NOT NULL DEFAULT 'Monthly'")
    op.execute("ALTER TABLE payslips ADD COLUMN IF NOT EXISTS regular_hours REAL NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE payslips ADD COLUMN IF NOT EXISTS overtime_hours REAL NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE payslips ADD COLUMN IF NOT EXISTS overtime_pay NUMERIC(12,2) NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE payslips ADD COLUMN IF NOT EXISTS bonus_amount NUMERIC(12,2) NOT NULL DEFAULT 0")

    # Migrate currency columns from REAL to NUMERIC(12,2)
    # Check each column in information_schema first to avoid unnecessary locks
    _migrate_currency_columns = [
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
    ]

    for tbl, col in _migrate_currency_columns:
        # Alembic's op.execute() doesn't directly support conditional checks in a Python loop,
        # so we perform each conversion unconditionally. The IF NOT EXISTS on the column
        # definition ensures idempotence, but for an actual TYPE conversion we need different
        # logic. For safety, we wrap it in a try/except pattern via raw SQL.
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='{tbl}' AND column_name='{col}'
                      AND data_type='numeric' AND numeric_precision=12 AND numeric_scale=2
                ) THEN
                    -- Already numeric, skip conversion
                    NULL;
                ELSE
                    -- Convert to numeric
                    ALTER TABLE {tbl} ALTER COLUMN {col} TYPE NUMERIC(12,2) USING {col}::numeric(12,2);
                END IF;
            END $$
        """)

    # Performance management tables
    op.execute("""
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

    op.execute("""
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

    op.execute("""
        CREATE TABLE IF NOT EXISTS okr_key_results (
            id              SERIAL  PRIMARY KEY,
            goal_id         INTEGER NOT NULL REFERENCES goals(id),
            description     TEXT    NOT NULL,
            target_value    REAL    NOT NULL DEFAULT 100,
            actual_value    REAL    NOT NULL DEFAULT 0
        )
    """)

    op.execute("""
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

    op.execute("""
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

    op.execute("""
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

    # Enable RLS on every tenant-scoped table (system_notifications is deliberately excluded)
    _rls_tables = [
        "institutions", "users", "employees", "audit_logs", "job_requisitions",
        "candidates", "interviews", "interview_scores", "offers",
        "candidate_audit_log", "ob_audit_log", "hr_notes",
        "ob_templates", "ob_checklists", "ob_checklist_items",
        "ld_courses", "ld_enrollments", "ld_audit_log",
        "ld_quizzes", "ld_quiz_questions", "ld_quiz_attempts",
        "ld_course_modules", "ld_lesson_progress",
        "holidays", "leave_types", "leave_balances", "leave_applications", "leave_audit_log",
        "projects", "project_tasks", "timesheets", "timesheet_entries", "timesheet_audit_log",
        "task_assignments", "institution_notifications",
        "payroll_runs", "payslips",
        "performance_cycles", "goals", "okr_key_results", "appraisals", "appraisal_audit_log", "performance_payouts",
    ]

    for tbl in _rls_tables:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_class
                    WHERE relnamespace='public'::regnamespace AND relname='{tbl}'
                      AND relrowsecurity IS FALSE
                ) THEN
                    ALTER TABLE public.{tbl} ENABLE ROW LEVEL SECURITY;
                END IF;
            END $$
        """)


def downgrade() -> None:
    # Drop all tables in reverse dependency order
    tables_to_drop = [
        # Performance management (depends on nothing)
        "performance_payouts", "appraisal_audit_log", "appraisals",
        "okr_key_results", "goals", "performance_cycles",

        # Payroll (depends on performance_payouts)
        "payslips", "payroll_runs",

        # Notifications
        "system_notifications", "institution_notifications",

        # Tasks/Projects/Timesheets
        "task_assignments", "timesheet_audit_log", "timesheet_entries",
        "timesheets", "project_tasks", "projects",

        # Leave
        "leave_audit_log", "leave_applications", "leave_balances", "leave_types",
        "holidays",

        # Learning & Development
        "ld_lesson_progress", "ld_course_modules", "ld_quiz_attempts",
        "ld_quiz_questions", "ld_quizzes", "ld_audit_log", "ld_enrollments", "ld_courses",

        # Onboarding
        "ob_checklist_items", "ob_checklists", "ob_audit_log", "ob_templates",

        # HR Notes
        "hr_notes",

        # Recruitment
        "candidate_audit_log", "interview_scores", "interviews", "offers", "candidates",
        "job_requisitions",

        # Core
        "audit_logs", "employees", "users", "institutions",
    ]

    for tbl in tables_to_drop:
        op.execute(f"DROP TABLE IF EXISTS public.{tbl} CASCADE")

    # Drop the trigger function
    op.execute("DROP FUNCTION IF EXISTS set_updated_at() CASCADE")
