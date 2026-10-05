"""Recruitment module: Job Requisitions, Candidates/ATS, Interviews, and Offers."""
import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from string import Template
from typing import Any, Dict, List, Optional

import anthropic
import redis
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ValidationError, field_validator

from core.deps import get_current_user, need_inst

from core.validators import validate_document_data_url, validate_ai_extractable_data_url

from core.approval_workflow import start_workflow, advance_or_finalize

from core.anthropic_client import get_client_for_institution

from core.ai_usage import FEATURE_RESUME_EXTRACTION, log_ai_usage, tokens_from_response

from db import get_db, IntegrityError

from core.db_session import db_session
from core.audit import diff_rows, write_entity_audit

from core.permission_matrix import require_permission

logger = logging.getLogger("ems")

router = APIRouter()

CANDIDATE_STAGES  = ["New","Screening","Interview","Pending Checks","Offer","Hired","Rejected by Candidate","Rejected by Company","Withdrawn"]
INTERVIEW_TYPES   = ["Phone","Video","In-Person","Technical","Panel"]
OFFER_TYPES       = ["Offer","Decline","Confirmation"]
OFFER_STATUSES    = ["Draft","Sent","Accepted","Rejected","Withdrawn"]
INTERVIEW_STATUSES= ["Scheduled","Completed","Cancelled","No-Show"]
REQ_STATUSES      = ["Draft","Pending Approval","Approved","Rejected","Closed","Filled"]
PRIORITIES        = ["Low","Normal","High","Urgent"]
SOURCES           = ["Direct","JobStreet","LinkedIn","Indeed","Referral","Agency","Walk-In","Other"]
QUALIFICATIONS    = ["SPM","STPM","Diploma","Bachelor's Degree","Master's Degree","PhD","Professional Cert","Other"]
SCORE_LABELS      = ["technical_score","communication_score","attitude_score","culture_fit_score","overall_score"]

# ---------------------------------------------------------------------------
# Resume AI extraction (Add Candidate's "Extract with AI" button) — reuses
# the same BYOK-or-platform Anthropic client resolution as the chatbot
# (routers/assistant.py), but inverted: a single *forced* tool call whose
# input_schema is the candidate-fields schema, so Claude returns structured
# data instead of choosing from a set of read tools. Nothing here is
# persisted (no audit log entry either) — same "ephemeral, not logged"
# treatment as the read-only assistant chat (see CLAUDE.md), since this
# endpoint only reads an uploaded file and returns field values; nothing is
# written until the HR user actually submits the Add Candidate form, which
# already logs normally via _log_candidate.
# ---------------------------------------------------------------------------
EXTRACT_RESUME_MODEL = "claude-haiku-4-5"
EXTRACT_RESUME_RATE_LIMIT_PER_HOUR = 5

_redis = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

EXTRACT_CANDIDATE_TOOL = {
    "name": "extract_candidate_fields",
    "description": (
        "Record the candidate profile fields found in the attached resume/CV. Only include a "
        "field if the resume actually states (or, for experience_years, clearly implies via "
        "work history dates) it — omit anything not actually present. Never invent or guess a "
        "value."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "full_name": {"type": "string"},
            "email": {"type": "string"},
            "phone": {"type": "string"},
            "ic_number": {"type": "string", "description": "Malaysian IC number, only if explicitly present"},
            "nationality": {"type": "string"},
            "gender": {"type": "string", "enum": ["Male", "Female"]},
            "date_of_birth": {"type": "string", "description": "YYYY-MM-DD, only if explicitly stated"},
            "address": {"type": "string"},
            "current_position": {"type": "string", "description": "Most recent or current job title"},
            "current_company": {"type": "string", "description": "Most recent or current employer"},
            "experience_years": {"type": "integer", "description": "Total years of professional experience"},
            "employment_history": {"type": "string", "description": "Brief summary of roles, companies, and achievements, most recent first"},
            "highest_qualification": {"type": "string", "enum": QUALIFICATIONS},
            "field_of_study": {"type": "string"},
            "institution_name": {"type": "string", "description": "University/institution of the highest qualification"},
            "graduation_year": {"type": "integer"},
            "certifications": {"type": "string"},
            "skills": {"type": "string", "description": "Comma-separated list of key skills"},
            "resume_text": {"type": "string", "description": "A clean plain-text summary of the resume's full content"},
            "linkedin_url": {"type": "string"},
        },
        "additionalProperties": False,
    },
}


def _enforce_extract_resume_rate_limit(user: dict) -> None:
    bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    key = f"recruitment_extract_resume_rl:{user['id']}:{bucket}"
    try:
        count = _redis.incr(key)
        if count == 1:
            _redis.expire(key, 3600)
    except redis.RedisError:
        logger.warning("resume extraction rate limit check failed (redis unavailable) - failing open")
        return
    if count > EXTRACT_RESUME_RATE_LIMIT_PER_HOUR:
        raise HTTPException(429, "You've reached the hourly limit for AI resume extraction. Try again later, or fill in the fields manually.")


def _parse_data_url(data_url: str) -> tuple:
    """data:<mime>;base64,<payload> -> (mime, payload). Callers already ran
    this through validate_ai_extractable_data_url, which only accepts a
    fixed, known-good prefix set, so the split here is never hit with
    anything malformed."""
    header, _, payload = data_url.partition(",")
    mime = header[len("data:"):].split(";")[0]
    return mime, payload

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
    email: str
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

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v):
        v = (v or "").strip()
        if not v or "@" not in v or v.startswith("@") or v.endswith("@"):
            raise ValueError("email must be a valid email address")
        return v


class CandidateDocumentIn(BaseModel):
    file_name: str
    mime_type: str
    data_url: str  # data:...;base64 URI, same pattern as institution logo / leave attachment

    @field_validator("data_url")
    @classmethod
    def _validate_data_url(cls, v):
        v = validate_document_data_url(v)
        if not v:
            raise ValueError("data_url is required")
        return v


class ExtractResumeIn(BaseModel):
    data_url: str  # data:application/pdf or data:image/... — see AI_EXTRACTABLE_MIME_PREFIXES

    @field_validator("data_url")
    @classmethod
    def _validate_data_url(cls, v):
        v = validate_ai_extractable_data_url(v)
        if not v:
            raise ValueError("data_url is required")
        return v


class ExtractedCandidateFields(BaseModel):
    """Every field here mirrors a CandidateIn field the Add Candidate form
    can populate from a resume — deliberately excludes requisition_id,
    source, expected_salary, notice_period, referral_by, notes, which a
    resume doesn't reliably state and which stay HR-entered. All Optional:
    the model is told to omit, not guess, anything not actually in the
    resume, and the frontend only fills blank fields with whatever comes
    back (see fillBlankCandidateFields in static/js/recruitment.js)."""
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    ic_number: Optional[str] = None
    nationality: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    address: Optional[str] = None
    current_position: Optional[str] = None
    current_company: Optional[str] = None
    experience_years: Optional[int] = None
    employment_history: Optional[str] = None
    highest_qualification: Optional[str] = None
    field_of_study: Optional[str] = None
    institution_name: Optional[str] = None
    graduation_year: Optional[int] = None
    certifications: Optional[str] = None
    skills: Optional[str] = None
    resume_text: Optional[str] = None
    linkedin_url: Optional[str] = None


class ExtractResumeOut(BaseModel):
    fields: ExtractedCandidateFields


class CandidateStageIn(BaseModel):
    stage: str
    notes: Optional[str] = None


class CandidateApplyIn(BaseModel):
    """Body for POST /candidates/{cand_id}/apply — applying an EXISTING
    person to another requisition (see 20260930_0002_add_candidate_requisitions
    and this endpoint's own docstring). Deliberately only the
    application-level fields — the person's profile (name, IC, resume,
    etc) is already on their candidates row and isn't re-submitted here."""
    requisition_id: Optional[int] = None
    source: str = "Direct"
    notes: Optional[str] = None
    expected_salary: Optional[float] = None
    notice_period: Optional[str] = None
    referral_by: Optional[str] = None


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
    # Exactly one of candidate_id/employee_id, per offer_type: Offer/Decline
    # are about a recruitment candidate; Confirmation (probation passed) is
    # about an existing employee — see offers.employee_id's migration.
    candidate_id: Optional[int] = None
    employee_id: Optional[str] = None
    requisition_id: Optional[int] = None
    offer_type: str = "Offer"
    salary_offered: Optional[float] = None
    start_date: Optional[str] = None
    expiry_date: Optional[str] = None
    letter_content: Optional[str] = None
    # Which offer_letter_templates row to render from — the offer_type's
    # own default template (creating it lazily if none exists yet) when
    # omitted. Ignored if letter_content is explicitly provided.
    template_id: Optional[int] = None


class OfferStatusIn(BaseModel):
    status: str


class OfferLetterTemplateIn(BaseModel):
    offer_type: str
    name: str
    body: str
    is_default: bool = False


def _log_candidate(conn, inst_id: int, cand_id: int, action: str, detail: str, by: str):
    conn.execute(
        "INSERT INTO candidate_audit_log (institution_id,candidate_id,action,detail,performed_by) VALUES (?,?,?,?,?)",
        (inst_id, cand_id, action, detail, by)
    )


def _log_requisition(conn, inst_id: int, req_id: int, action: str, detail: str, user: dict):
    conn.execute(
        "INSERT INTO requisition_audit_log (institution_id,requisition_id,action,detail,performed_by,performer_role) VALUES (?,?,?,?,?,?)",
        (inst_id, req_id, action, detail, user["username"], user["role"])
    )


# Every editable field on a requisition (create_requisition's own INSERT
# column list) — used by update_requisition to log exactly which fields
# actually changed, not just a generic "Requisition updated".
_REQUISITION_DIFF_FIELDS = (
    "title", "department", "headcount", "employment_type",
    "description", "requirements", "salary_min", "salary_max", "priority",
)


def _requisition_edit_detail(old_row, new_body) -> str:
    changes = []
    for field in _REQUISITION_DIFF_FIELDS:
        old_val, new_val = old_row[field], getattr(new_body, field)
        if old_val != new_val:
            changes.append(f"{field}: {old_val!r} → {new_val!r}")
    return "; ".join(changes) if changes else "No fields changed"


def _log_employee_note(conn, inst_id: int, employee_id: str, body: str, by: str):
    """Confirmation letters are about an employee, not a candidate — there's
    no candidate_audit_log to write to, so this uses hr_notes instead,
    same table/shape routers/employees.py already uses for its own
    system-generated "Employee record created/updated" entries."""
    conn.execute(
        "INSERT INTO hr_notes (institution_id, employee_id, note_type, body, created_by) VALUES (?,?,?,?,?)",
        (inst_id, employee_id, "general", body, by)
    )


def _transition_candidate_stage(conn, inst_id: int, cand_id: int, requisition_id, new_stage: str):
    """The single place a candidate_requisitions row's stage is ever
    written, so candidate_stage_history (used for "time spent per stage" —
    the candidate detail Time in Stage tab and the recruitment dashboard's
    per-stage averages) can never drift out of sync with it. Closes
    whatever stage row is currently open for THIS application (there's at
    most one per (candidate, requisition) pair — see
    20260930_0002_add_candidate_requisitions) and opens a new one.
    requisition_id may be None (a "general interest" application not tied
    to a specific opening) — `IS NOT DISTINCT FROM` throughout so that
    compares correctly instead of the usual SQL "NULL <> NULL is unknown"
    trap.

    Used to also dual-write a `candidates.stage` mirror column (Phase 2)
    for the pre-Phase-3 frontend — removed once Phase 3 read
    candidate_requisitions directly and Phase 4's migration
    (20261001_0001_drop_candidates_legacy_application_columns) dropped the
    column entirely. `_candidate_with_derived_fields` is the read-side
    equivalent now: it derives a candidate's "current" stage/requisition
    from their sole application when they have exactly one."""
    conn.execute(
        "UPDATE candidate_stage_history SET exited_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') "
        "WHERE candidate_id=? AND requisition_id IS NOT DISTINCT FROM ? AND institution_id=? AND exited_at IS NULL",
        (cand_id, requisition_id, inst_id)
    )
    conn.execute(
        "INSERT INTO candidate_stage_history (institution_id,candidate_id,requisition_id,stage) VALUES (?,?,?,?)",
        (inst_id, cand_id, requisition_id, new_stage)
    )
    conn.execute(
        "UPDATE candidate_requisitions SET stage=? "
        "WHERE candidate_id=? AND requisition_id IS NOT DISTINCT FROM ? AND institution_id=?",
        (new_stage, cand_id, requisition_id, inst_id)
    )


def _get_candidate(conn, inst_id, cand_id):
    row = conn.execute(
        "SELECT * FROM candidates WHERE id=? AND institution_id=?", (cand_id, inst_id)
    ).fetchone()
    if not row: raise HTTPException(404, "Candidate not found")
    return dict(row)


def _sole_application(conn, inst_id, cand_id):
    """The candidate's one application (candidate_requisitions row, plus
    its requisition's title/department), if and only if they have exactly
    one — the same "unambiguous when there's only one" resolution
    `_candidate_with_derived_fields`, `move_stage`, `schedule_interview`,
    and `create_offer` all rely on now that `candidates` itself carries no
    application-level columns of its own (see
    20260930_0002_add_candidate_requisitions and
    20261001_0001_drop_candidates_legacy_application_columns). Returns
    None for zero or multiple applications — there's no single answer to
    derive in either case."""
    apps = conn.execute("""
        SELECT cr.*, r.title AS requisition_title, r.department AS requisition_department
        FROM candidate_requisitions cr LEFT JOIN job_requisitions r ON r.id = cr.requisition_id
        WHERE cr.candidate_id=? AND cr.institution_id=?
    """, (cand_id, inst_id)).fetchall()
    return dict(apps[0]) if len(apps) == 1 else None


def _sole_application_requisition_id(conn, inst_id, cand_id):
    app = _sole_application(conn, inst_id, cand_id)
    return app["requisition_id"] if app else None


def _candidate_with_derived_fields(conn, inst_id, cand_id):
    """The person record (candidates.*) merged with the application-level
    view fields — stage/requisition_id/requisition/source/notes/
    expected_salary/notice_period/referral_by — that `candidates` itself
    used to carry directly pre-Phase-4. Derived from the candidate's sole
    application when they have exactly one (still true for virtually all
    data); left None once a person has more than one, since there's no
    single answer to show — the Applications section in Candidate Detail
    (static/js/recruitment.js) is the real multi-application view."""
    c = _get_candidate(conn, inst_id, cand_id)
    app = _sole_application(conn, inst_id, cand_id)
    for key in ("stage", "requisition_id", "source", "notes", "expected_salary", "notice_period", "referral_by"):
        c[key] = app[key] if app else None
    c["requisition"] = ({"id": app["requisition_id"], "title": app["requisition_title"], "department": app["requisition_department"]}
                         if app and app["requisition_id"] else None)
    return c


def _get_req(conn, inst_id, req_id):
    row = conn.execute(
        "SELECT * FROM job_requisitions WHERE id=? AND institution_id=?", (req_id, inst_id)
    ).fetchone()
    if not row: raise HTTPException(404, "Requisition not found")
    return dict(row)


def _get_employee_for_letter(conn, inst_id, employee_id):
    row = conn.execute(
        "SELECT * FROM employees WHERE employee_id=? AND institution_id=?", (employee_id, inst_id)
    ).fetchone()
    if not row: raise HTTPException(404, "Employee not found")
    return dict(row)


def _requisition_requester_employee_id(conn, inst_id, req):
    """Job requisitions have no requester employee column of their own
    (they're always created by an HR/recruiter user, not a line manager) —
    the approval workflow's Direct/Skip-Level Manager steps resolve from
    whichever employee record is linked to the creating user's account."""
    u = conn.execute(
        "SELECT employee_id FROM users WHERE username=? AND institution_id=?",
        (req["created_by"], inst_id)
    ).fetchone()
    return u["employee_id"] if u else None


# Institutions get one of each lazily (see _get_or_create_default_offer_template)
# rather than being seeded up front — same resolve-or-create-default pattern
# as get_or_create_default_workflow (core/approval_workflow.py) and onboarding's
# template sets. Wording here is exactly what the old hardcoded
# _gen_offer_letter f-strings produced, just parameterized.
_DEFAULT_OFFER_LETTER_TEMPLATE_BODY = """[COMPANY LETTERHEAD]

${today}

${candidate_name}
${candidate_email}

Dear ${candidate_name},

LETTER OF OFFER — ${position}

We are pleased to offer you the position of ${position} in the ${department} department on the following terms and conditions:

Position         : ${position}
Department       : ${department}
Employment Type  : ${employment_type}
Basic Salary     : ${salary_offered}
Commencement Date: ${start_date}

Your appointment will be subject to:
1. Satisfactory completion of our pre-employment medical examination.
2. Submission of all required original documents for verification.
3. Compliance with the Company's policies, rules and regulations.

This offer is valid until ${expiry_date}.

To accept this offer, please sign and return one copy of this letter by the expiry date stated above.

We look forward to welcoming you to our team.

Yours sincerely,


_______________________
Human Resources
[Company Name]


I, ${candidate_name}, hereby accept the above offer of employment.

Signature: _______________________    Date: _______________
"""

_DEFAULT_DECLINE_LETTER_TEMPLATE_BODY = """[COMPANY LETTERHEAD]

${today}

${candidate_name}
${candidate_email}

Dear ${candidate_name},

RE: Application for ${position}

Thank you for your interest in the above position and for the time you invested in our recruitment process.

After careful consideration of all applications received, we regret to inform you that we are unable to offer you a position at this time. This was a difficult decision as we received many strong applications.

We appreciate the effort you put into your application and encourage you to apply for future vacancies that match your profile.

We wish you every success in your career endeavours.

Yours sincerely,


_______________________
Human Resources
[Company Name]
"""

# Confirmation: sent to an existing *employee* once HR decides they've
# passed probation (Employee detail page's "Confirm Probation" action) —
# unlike Offer/Decline, there's no candidate/requisition behind it, so it
# renders from the employee's own record instead (see _offer_letter_context).
_DEFAULT_CONFIRMATION_LETTER_TEMPLATE_BODY = """[COMPANY LETTERHEAD]

${today}

${recipient_name}
${recipient_email}

Dear ${recipient_name},

RE: Confirmation of Employment — ${position}

We are pleased to inform you that, following the successful completion of your probationary period (ended ${probation_end_date}), your employment as ${position} in the ${department} department has been confirmed with effect from ${today}.

All other terms and conditions of your employment remain unchanged.

We look forward to your continued contribution to the team.

Yours sincerely,


_______________________
Human Resources
[Company Name]
"""


def _fmt_letter_date(value: Optional[str]) -> str:
    """Formats a "YYYY-MM-DD..." date value for display inside a letter
    body, matching ${today}'s own "10 September 2026" style — every date
    placeholder in a letter should read the same way. Before this, only
    ${today} was ever formatted; ${start_date}/${expiry_date}/
    ${probation_end_date} were passed through as raw DB strings, so a
    printed letter read inconsistently within itself (a nicely-written
    date up top, then "Commencement Date: 2026-09-10" further down).
    Returns "" for a missing value, matching every other optional
    placeholder in _offer_letter_context — safe_substitute then just
    leaves that spot blank rather than printing "None"."""
    if not value:
        return ""
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").strftime("%d %B %Y")
    except ValueError:
        return str(value)  # not a recognizable date — pass through, don't mangle


def _offer_letter_context(cand, req, offer, emp=None) -> Dict[str, str]:
    """Placeholder values ($name / ${name} in a template body — see
    string.Template) available to every letter template, regardless of
    offer_type. Unused placeholders are simply left as literal text by
    safe_substitute, and unknown/extra dict keys are ignored, so templates
    don't need to reference every key here.

    emp is set instead of cand for a Confirmation letter (about an existing
    employee, not a recruitment candidate) — recipient_name/recipient_email
    are the type-agnostic names for who the letter addresses; candidate_name/
    candidate_email are kept as aliases pointing at the same values so
    Offer/Decline templates written before this existed keep working
    unchanged."""
    salary = offer.get("salary_offered")
    if emp:
        name = emp["full_name"]
        email = emp.get("work_email") or emp.get("personal_email") or ""
        position = emp.get("designation") or "your role"
        department = emp.get("department") or ""
        employment_type = emp.get("employment_type") or ""
        start_date = offer.get("start_date") or emp.get("start_date") or ""
    else:
        name = cand["full_name"]
        email = cand.get("email", "") or ""
        position = (req.get("title") if req else None) or "the position"
        department = (req.get("department") if req else None) or ""
        employment_type = (req.get("employment_type") if req else None) or ""
        start_date = offer.get("start_date") or ""
    return {
        "recipient_name": name,
        "recipient_email": email,
        "candidate_name": name,
        "candidate_email": email,
        "today": datetime.now().strftime("%d %B %Y"),
        "position": position,
        "department": department,
        "employment_type": employment_type,
        "salary_offered": f"RM {salary:,.2f} per month" if salary else "",
        "start_date": _fmt_letter_date(start_date),
        "expiry_date": _fmt_letter_date(offer.get("expiry_date")),
        "offer_type": offer.get("offer_type", ""),
        "probation_end_date": _fmt_letter_date(emp.get("probation_end_date") if emp else None),
    }


def _render_offer_letter(template_body: str, cand, req, offer, emp=None) -> str:
    return Template(template_body).safe_substitute(_offer_letter_context(cand, req, offer, emp))


_DEFAULT_LETTER_TEMPLATE_BODIES = {
    "Offer": _DEFAULT_OFFER_LETTER_TEMPLATE_BODY,
    "Decline": _DEFAULT_DECLINE_LETTER_TEMPLATE_BODY,
    "Confirmation": _DEFAULT_CONFIRMATION_LETTER_TEMPLATE_BODY,
}


def _get_or_create_default_offer_template(conn, inst_id: int, offer_type: str) -> Dict[str, Any]:
    """This institution's default template for offer_type, creating one
    (seeded from the wording _gen_offer_letter used to hardcode) the first
    time it's needed."""
    row = conn.execute(
        "SELECT * FROM offer_letter_templates WHERE institution_id=? AND offer_type=? "
        "ORDER BY is_default DESC, id LIMIT 1",
        (inst_id, offer_type)
    ).fetchone()
    if row:
        return dict(row)
    body = _DEFAULT_LETTER_TEMPLATE_BODIES[offer_type]
    conn.execute(
        "INSERT INTO offer_letter_templates (institution_id,offer_type,name,body,is_default) VALUES (?,?,?,?,1)",
        (inst_id, offer_type, f"Default {offer_type} Letter", body)
    )
    tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    return dict(conn.execute("SELECT * FROM offer_letter_templates WHERE id=?", (tid,)).fetchone())


# ---------------------------------------------------------------------------
# Recruitment — Job Requisitions
# ---------------------------------------------------------------------------
@router.get("/api/recruitment/requisitions")
@db_session
def list_requisitions(conn, 
    status: Optional[str] = None,
    department: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    require_permission(conn, user, "recruitment.view_requisitions_candidates_interviews_offers")
    inst_id = need_inst(user)
    q = """
        SELECT r.*,
            (SELECT COUNT(*) FROM candidate_requisitions cr
              WHERE cr.requisition_id=r.id AND cr.stage NOT IN ('Rejected by Candidate','Rejected by Company','Withdrawn')) AS candidate_count,
            (SELECT COUNT(*) FROM candidate_requisitions cr
              WHERE cr.requisition_id=r.id AND cr.stage IN ('Screening','Interview','Pending Checks','Offer','Hired')) AS shortlisted_count,
            (SELECT COUNT(DISTINCT i.candidate_id) FROM interviews i
              WHERE i.requisition_id=r.id AND i.status='Completed') AS interviewed_count,
            (SELECT COUNT(*) FROM candidate_requisitions cr
              WHERE cr.requisition_id=r.id AND cr.stage IN ('Offer','Hired')) AS offer_count
        FROM job_requisitions r WHERE r.institution_id=?
    """
    p = [inst_id]
    if status:     q += " AND r.status=?";     p.append(status)
    if department: q += " AND r.department=?"; p.append(department)
    q += " ORDER BY r.created_at DESC"
    rows = conn.execute(q, p).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/recruitment/requisitions", status_code=201)
@db_session
def create_requisition(conn, body: RequisitionIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    inst_id = need_inst(user)
    conn.execute("""
        INSERT INTO job_requisitions (institution_id,title,department,headcount,employment_type,
            description,requirements,salary_min,salary_max,priority,created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (inst_id, body.title, body.department, body.headcount, body.employment_type,
          body.description, body.requirements, body.salary_min, body.salary_max,
          body.priority, user["username"]))
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    _log_requisition(conn, inst_id, rid, "Created", f"Requisition '{body.title}' created ({body.headcount} headcount)", user)
    conn.commit()
    row = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (rid,)).fetchone()
    return dict(row)


@router.get("/api/recruitment/requisitions/{req_id}")
@db_session
def get_requisition(conn, req_id: int, user: dict = Depends(get_current_user)) -> Optional[Dict[str, Any]]:
    require_permission(conn, user, "recruitment.view_requisitions_candidates_interviews_offers")
    inst_id = need_inst(user)
    r = _get_req(conn, inst_id, req_id)
    # Reads candidate_requisitions (per-application), not candidates — a
    # person who applied here via POST .../apply shows up too, which a
    # candidates-table query never could (candidates carries no
    # application-level columns at all since Phase 4 — see
    # 20261001_0001_drop_candidates_legacy_application_columns).
    cands = conn.execute("""
        SELECT cr.candidate_id AS id, c.full_name, cr.stage, cr.source, cr.created_at
        FROM candidate_requisitions cr JOIN candidates c ON c.id = cr.candidate_id
        WHERE cr.requisition_id=? AND cr.institution_id=? ORDER BY cr.created_at DESC
    """, (req_id, inst_id)).fetchall()
    r["candidates"] = [dict(c) for c in cands]
    return r


@router.put("/api/recruitment/requisitions/{req_id}")
@db_session
def update_requisition(conn, req_id: int, body: RequisitionIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    inst_id = need_inst(user)
    r = _get_req(conn, inst_id, req_id)
    if r["status"] not in ("Draft",):
        raise HTTPException(400, "Only Draft requisitions can be edited")
    edit_detail = _requisition_edit_detail(r, body)
    conn.execute("""
        UPDATE job_requisitions SET title=?,department=?,headcount=?,employment_type=?,
            description=?,requirements=?,salary_min=?,salary_max=?,priority=?
        WHERE id=? AND institution_id=?
    """, (body.title, body.department, body.headcount, body.employment_type,
          body.description, body.requirements, body.salary_min, body.salary_max,
          body.priority, req_id, inst_id))
    _log_requisition(conn, inst_id, req_id, "Updated", edit_detail, user)
    conn.commit()
    row = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (req_id,)).fetchone()
    return dict(row)


@router.patch("/api/recruitment/requisitions/{req_id}/submit")
@db_session
def submit_requisition(conn, req_id: int, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    inst_id = need_inst(user)
    r = _get_req(conn, inst_id, req_id)
    if r["status"] != "Draft":
        raise HTTPException(400, "Only Draft requisitions can be submitted")
    # requester_employee_id may be None (the creating user has no linked
    # employee record — common for HR/recruiter accounts) — start_workflow
    # handles that fine on its own: direct_manager/skip_level_manager steps
    # simply resolve to nobody and get auto-skipped, while hr_manager steps
    # don't need an employee at all, so this must NOT be treated as "no
    # resolvable step anywhere" up front.
    requester_employee_id = _requisition_requester_employee_id(conn, inst_id, r)
    workflow_id, step_order, auto_approved = start_workflow(conn, inst_id, "requisition", requester_employee_id)
    new_status = "Approved" if auto_approved else "Pending Approval"
    conn.execute("UPDATE job_requisitions SET status=?,approval_workflow_id=?,approval_step=? WHERE id=?",
                 (new_status, workflow_id, step_order, req_id))
    _log_requisition(conn, inst_id, req_id, "Submitted",
                     "Auto-approved (no applicable approval step)" if auto_approved else "Submitted for approval", user)
    conn.commit()
    row = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (req_id,)).fetchone()
    return dict(row)


@router.patch("/api/recruitment/requisitions/{req_id}/approve")
@db_session
def approve_requisition(conn, req_id: int, body: RequisitionApprovalIn,
                         user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    r = _get_req(conn, inst_id, req_id)
    if r["status"] != "Pending Approval":
        raise HTTPException(400, "Requisition is not pending approval")
    if body.action not in ("approve","reject"):
        raise HTTPException(400, "Action must be approve or reject")
    action = "reject" if body.action == "reject" else "approve"
    requester_employee_id = _requisition_requester_employee_id(conn, inst_id, r)
    if r["approval_workflow_id"] and r["approval_step"] is not None:
        try:
            outcome, next_step = advance_or_finalize(
                conn, inst_id, "requisition", requester_employee_id,
                r["approval_workflow_id"], r["approval_step"], action, user,
                "job_requisitions", req_id
            )
        except PermissionError as e:
            raise HTTPException(403, str(e))
    else:
        if user["role"] not in ("superadmin", "hr_manager"):
            raise HTTPException(403, "Only HR Manager can approve/reject requisitions")
        outcome, next_step = ("rejected" if action == "reject" else "approved"), None

    step_label = f"step {r['approval_step']}" if r["approval_step"] is not None else "the approval"
    comment_suffix = f" — {body.comments}" if body.comments else ""

    if outcome == "advanced":
        conn.execute("UPDATE job_requisitions SET approval_step=?,approval_comments=? WHERE id=?",
                     (next_step, body.comments, req_id))
        _log_requisition(conn, inst_id, req_id, "Approval Advanced",
                         f"Cleared {step_label}, now awaiting step {next_step}{comment_suffix}", user)
        conn.commit()
        return dict(conn.execute("SELECT * FROM job_requisitions WHERE id=?", (req_id,)).fetchone())

    new_status = "Approved" if outcome == "approved" else "Rejected"
    # approved_by must only ever name the person who actually approved —
    # leave it NULL on rejection so the "Approved By" block doesn't render
    # for a rejected requisition (who rejected it, and why, is still fully
    # captured in requisition_audit_log via the History section).
    approved_by = user["username"] if outcome == "approved" else None
    conn.execute("""
        UPDATE job_requisitions SET status=?, approved_by=?, approval_comments=?, approval_step=NULL
        WHERE id=?
    """, (new_status, approved_by, body.comments, req_id))
    _log_requisition(conn, inst_id, req_id, new_status,
                     f"{'Approved' if outcome == 'approved' else 'Rejected'} at {step_label}{comment_suffix}", user)
    conn.commit()
    row = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (req_id,)).fetchone()
    return dict(row)


@router.patch("/api/recruitment/requisitions/{req_id}/close")
@db_session
def close_requisition(conn, req_id: int, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    inst_id = need_inst(user)
    conn.execute(
        "UPDATE job_requisitions SET status='Closed', closed_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=? AND institution_id=?",
        (req_id, inst_id)
    )
    _log_requisition(conn, inst_id, req_id, "Closed", "Requisition closed", user)
    conn.commit()
    row = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (req_id,)).fetchone()
    return dict(row)


@router.post("/api/recruitment/requisitions/{req_id}/public-link")
@db_session
def enable_public_link(conn, req_id: int, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Generates (or returns the existing) public application token for this
    requisition — see 20261001_0002_add_requisition_public_token and
    routers/public_careers.py, the only place this token is ever read by an
    unauthenticated caller. Only an Approved requisition can be made public
    — that's already this app's "open for hiring" signal (the same status
    static/js/dashboard.js's Open Roles KPI counts) — but routers/
    public_careers.py re-checks status live on every request too, so a
    requisition closed afterward stops accepting applications immediately
    without needing to also revoke the token here."""
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    inst_id = need_inst(user)
    req = _get_req(conn, inst_id, req_id)
    if req["status"] != "Approved":
        raise HTTPException(400, "Only an Approved requisition can accept public applications")
    token = req.get("public_token")
    if not token:
        token = str(uuid.uuid4())
        conn.execute("UPDATE job_requisitions SET public_token=? WHERE id=? AND institution_id=?", (token, req_id, inst_id))
        _log_requisition(conn, inst_id, req_id, "Public Applications Enabled", "Public application link generated", user)
        conn.commit()
    return {"public_token": token}


@router.delete("/api/recruitment/requisitions/{req_id}/public-link")
@db_session
def disable_public_link(conn, req_id: int, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Revokes the public application link — any previously-shared URL
    stops working immediately and permanently; re-enabling issues a brand
    new token, never reuses the old one."""
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    inst_id = need_inst(user)
    _get_req(conn, inst_id, req_id)
    conn.execute("UPDATE job_requisitions SET public_token=NULL WHERE id=? AND institution_id=?", (req_id, inst_id))
    _log_requisition(conn, inst_id, req_id, "Public Applications Disabled", "Public application link revoked", user)
    conn.commit()
    return {"ok": True}


@router.get("/api/recruitment/requisitions/{req_id}/audit-log")
@db_session
def get_requisition_audit_log(conn, req_id: int, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    require_permission(conn, user, "recruitment.view_requisition_audit_log")
    inst_id = need_inst(user)
    _get_req(conn, inst_id, req_id)
    rows = conn.execute(
        "SELECT * FROM requisition_audit_log WHERE requisition_id=? AND institution_id=? ORDER BY created_at DESC",
        (req_id, inst_id)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Recruitment — Candidates / ATS
# ---------------------------------------------------------------------------
CANDIDATE_SORT_COLUMNS = {
    "full_name": "c.full_name",
    "requisition_title": "r.title",
    "requisition_status": "r.status",
    "source": "cr.source",
    "created_at": "cr.created_at",
    "experience_years": "c.experience_years",
    "last_interview_date": "last_interview_date",
    "stage": "cr.stage",
}


@router.get("/api/recruitment/candidates")
@db_session
def list_candidates(conn, response: Response,
    requisition_id: Optional[int] = None,
    stage: Optional[List[str]] = Query(None),
    search: Optional[str] = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: Optional[int] = None, offset: int = 0,
    user: dict = Depends(get_current_user),
):
    # limit is opt-in and defaults to None (today's "return everything"
    # behavior, unchanged) — the Interview/Offer "select candidate"
    # pickers (openIntModal/openOfferModal in recruitment.js) need the
    # full candidate list, not one page of it, so only the Candidate Bank
    # screen's own dedicated fetch passes limit/offset.
    #
    # One row per APPLICATION (candidate_requisitions), not per person —
    # matches list_requisitions'/get_requisition's own per-application
    # counts since Phase 2/3, and is the only sensible shape once a person
    # can have more than one open application with its own stage. A
    # candidate with 2 applications appears twice here, same candidate id
    # both times, each row its own stage/requisition — clicking either
    # opens the same Candidate Detail, whose Applications section (Phase 3)
    # shows both.
    require_permission(conn, user, "recruitment.view_requisitions_candidates_interviews_offers")
    inst_id = need_inst(user)
    q = """SELECT c.*, r.title AS requisition_title, r.status AS requisition_status, cr.requisition_id AS requisition_id,
               cr.stage AS stage, cr.source AS source, cr.created_at AS created_at,
               (SELECT MAX(i.scheduled_date) FROM interviews i
                 WHERE i.candidate_id=c.id AND i.requisition_id IS NOT DISTINCT FROM cr.requisition_id) AS last_interview_date
           FROM candidate_requisitions cr
           JOIN candidates c ON c.id = cr.candidate_id
           LEFT JOIN job_requisitions r ON r.id = cr.requisition_id
           WHERE cr.institution_id=?"""
    p = [inst_id]
    if requisition_id: q += " AND cr.requisition_id=?"; p.append(requisition_id)
    if stage is not None:
        if not stage:
            q += " AND FALSE"
        else:
            q += f" AND cr.stage IN ({','.join('?' for _ in stage)})"
            p.extend(stage)
    if search:
        like = f"%{search}%"
        q += " AND (c.full_name ILIKE ? OR c.email ILIKE ? OR c.current_company ILIKE ? OR c.skills ILIKE ?)"
        p.extend([like,like,like,like])

    if limit is not None:
        total = conn.execute(f"SELECT COUNT(*) FROM ({q}) AS sub", p).fetchone()[0]
        response.headers["X-Total-Count"] = str(total)

    sort_col = CANDIDATE_SORT_COLUMNS.get(sort_by, "c.created_at")
    direction = "ASC" if sort_dir == "asc" else "DESC"
    q += f" ORDER BY {sort_col} {direction} NULLS LAST"
    if limit is not None:
        limit = min(max(1, limit), 500)
        offset = max(0, offset)
        q += " LIMIT ? OFFSET ?"
        p = p + [limit, offset]
    rows = conn.execute(q, p).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/recruitment/candidates", status_code=201)
@db_session
def create_candidate(conn, body: CandidateIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    inst_id = need_inst(user)
    conn.execute("""
        INSERT INTO candidates (institution_id,full_name,email,phone,ic_number,
            nationality,gender,date_of_birth,address,current_position,current_company,
            experience_years,employment_history,highest_qualification,field_of_study,
            institution_name,graduation_year,certifications,skills,resume_text,
            linkedin_url,created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (inst_id, body.full_name, body.email, body.phone, body.ic_number,
          body.nationality, body.gender, body.date_of_birth, body.address,
          body.current_position, body.current_company, body.experience_years, body.employment_history,
          body.highest_qualification, body.field_of_study, body.institution_name, body.graduation_year,
          body.certifications, body.skills, body.resume_text, body.linkedin_url,
          user["username"]))
    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    # The candidate's first application — see 20260930_0002_add_candidate_requisitions.
    # The application-level fields (requisition/source/notes/salary/notice/
    # referral) live only here now, not on candidates — see
    # 20261001_0001_drop_candidates_legacy_application_columns.
    conn.execute("""
        INSERT INTO candidate_requisitions
            (institution_id,candidate_id,requisition_id,source,notes,
             expected_salary,notice_period,referral_by,created_by)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (inst_id, cid, body.requisition_id, body.source, body.notes,
          body.expected_salary, body.notice_period, body.referral_by, user["username"]))
    _transition_candidate_stage(conn, inst_id, cid, body.requisition_id, "New")
    _log_candidate(conn, inst_id, cid, "Created", f"Candidate '{body.full_name}' added via {body.source}", user["username"])
    conn.commit()
    return _candidate_with_derived_fields(conn, inst_id, cid)


@router.post("/api/recruitment/candidates/extract-resume")
async def extract_resume_fields(body: ExtractResumeIn, user: dict = Depends(get_current_user)) -> ExtractResumeOut:
    """Reads an uploaded resume (PDF or image, not yet attached to any
    candidate — this runs before the candidate exists) and asks Claude to
    pull out whatever Add Candidate fields it can find, powering that
    modal's "Extract with AI" button. Same write permission as creating
    the candidate itself, since this is part of that same flow."""
    _enforce_extract_resume_rate_limit(user)

    conn = get_db()
    try:
        require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
        inst_id = need_inst(user)
        anthropic_client = get_client_for_institution(conn, inst_id)
    finally:
        conn.close()

    if anthropic_client is None:
        raise HTTPException(400, "AI extraction isn't set up for your organization yet — ask your HR manager to configure it under Settings → AI Assistant, or fill in the fields manually.")

    mime, payload = _parse_data_url(body.data_url)
    content_block = {
        "type": "document" if mime == "application/pdf" else "image",
        "source": {"type": "base64", "media_type": mime, "data": payload},
    }

    try:
        resp = anthropic_client.messages.create(
            model=EXTRACT_RESUME_MODEL,
            max_tokens=1536,
            tools=[EXTRACT_CANDIDATE_TOOL],
            tool_choice={"type": "tool", "name": "extract_candidate_fields"},
            messages=[{
                "role": "user",
                "content": [
                    content_block,
                    {"type": "text", "text": "Extract the candidate's profile fields from this resume."},
                ],
            }],
        )
    except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        logger.warning(f"resume extraction: Anthropic API error: {e}")
        raise HTTPException(502, "Couldn't reach the AI extraction service right now — please try again shortly, or fill in the fields manually.")

    # Tokens were spent whether or not the response below turns out usable.
    in_tok, out_tok = tokens_from_response(resp)
    log_ai_usage(inst_id, user, FEATURE_RESUME_EXTRACTION, EXTRACT_RESUME_MODEL, in_tok, out_tok)

    tool_use = next((b for b in resp.content if b.type == "tool_use"), None)
    if not tool_use:
        raise HTTPException(502, "The AI couldn't extract any fields from this file — please fill in the fields manually.")
    try:
        fields = ExtractedCandidateFields(**tool_use.input)
    except ValidationError as e:
        logger.warning(f"resume extraction: tool_use input failed validation: {e}")
        raise HTTPException(502, "The AI's response couldn't be read — please fill in the fields manually.")
    return ExtractResumeOut(fields=fields)


@router.post("/api/recruitment/candidates/{cand_id}/apply", status_code=201)
@db_session
def apply_candidate_to_requisition(conn, cand_id: int, body: CandidateApplyIn,
                                   user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Applies an EXISTING person (found via the Candidate Bank search —
    see list_candidates' person-level mode, or GET .../candidates/search)
    to another requisition, without duplicating their profile into a new
    candidates row — the actual feature 20260930_0002_add_
    candidate_requisitions exists for. UNIQUE(candidate_id, requisition_id)
    (and the partial index for two NULL/"general interest" applications)
    turn a duplicate application into a clean 400 instead of a raw
    IntegrityError — see create_payroll_run for the same pattern."""
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    inst_id = need_inst(user)
    cand = _get_candidate(conn, inst_id, cand_id)
    if body.requisition_id:
        _get_req(conn, inst_id, body.requisition_id)  # 404s if not found/not this institution
    try:
        conn.execute("""
            INSERT INTO candidate_requisitions
                (institution_id,candidate_id,requisition_id,source,notes,
                 expected_salary,notice_period,referral_by,created_by)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (inst_id, cand_id, body.requisition_id, body.source, body.notes,
              body.expected_salary, body.notice_period, body.referral_by, user["username"]))
    except IntegrityError:
        raise HTTPException(400, "This candidate has already applied to that requisition"
                             if body.requisition_id else
                             "This candidate already has a general (not-tied-to-a-requisition) application")
    aid = conn._last_id
    _transition_candidate_stage(conn, inst_id, cand_id, body.requisition_id, "New")
    detail = f"Applied to requisition #{body.requisition_id}" if body.requisition_id else "Applied (general interest)"
    _log_candidate(conn, inst_id, cand_id, "Applied", f"{detail} — {cand['full_name']}", user["username"])
    conn.commit()
    row = conn.execute("""
        SELECT cr.*, r.title AS requisition_title FROM candidate_requisitions cr
        LEFT JOIN job_requisitions r ON r.id = cr.requisition_id
        WHERE cr.id=?
    """, (aid,)).fetchone()
    return dict(row)


@router.get("/api/recruitment/candidates/search")
@db_session
def search_candidates(conn, q: str, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Person-level lookup for "is this an existing candidate?" (Add
    Candidate's duplicate-detection search — Phase 3) — unlike
    list_candidates, which stays one-row-per-application for backward
    compatibility with the pre-Phase-3 frontend, this is always one row
    per PERSON, each with every application they currently have. Matches
    name/IC/email/phone; a bare 2-character q is rejected rather than
    returning the whole Candidate Bank."""
    inst_id = need_inst(user)
    if len(q.strip()) < 2:
        raise HTTPException(400, "Search term must be at least 2 characters")
    like = f"%{q.strip()}%"
    rows = conn.execute("""
        SELECT id,full_name,email,phone,ic_number,current_position,current_company
        FROM candidates
        WHERE institution_id=? AND (full_name ILIKE ? OR ic_number ILIKE ? OR email ILIKE ? OR phone ILIKE ?)
        ORDER BY full_name LIMIT 20
    """, (inst_id, like, like, like, like)).fetchall()
    people = [dict(r) for r in rows]
    if not people:
        return []
    ids = [p["id"] for p in people]
    apps = conn.execute(f"""
        SELECT cr.candidate_id, cr.requisition_id, cr.stage, r.title AS requisition_title
        FROM candidate_requisitions cr
        LEFT JOIN job_requisitions r ON r.id = cr.requisition_id
        WHERE cr.candidate_id IN ({','.join('?' * len(ids))}) AND cr.institution_id=?
        ORDER BY cr.created_at DESC
    """, (*ids, inst_id)).fetchall()
    apps_by_cand: Dict[int, List[Dict[str, Any]]] = {}
    for a in apps:
        apps_by_cand.setdefault(a["candidate_id"], []).append({
            "requisition_id": a["requisition_id"], "requisition_title": a["requisition_title"], "stage": a["stage"],
        })
    for p in people:
        p["applications"] = apps_by_cand.get(p["id"], [])
    return people


@router.get("/api/recruitment/candidates/{cand_id}")
@db_session
def get_candidate(conn, cand_id: int, user: dict = Depends(get_current_user)) -> Optional[Dict[str, Any]]:
    require_permission(conn, user, "recruitment.view_requisitions_candidates_interviews_offers")
    inst_id = need_inst(user)
    c = _candidate_with_derived_fields(conn, inst_id, cand_id)
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
    docs = conn.execute(
        "SELECT id,file_name,mime_type,data_url,uploaded_by,created_at FROM candidate_documents WHERE candidate_id=? AND institution_id=? ORDER BY created_at",
        (cand_id, inst_id)
    ).fetchall()
    c["interviews"] = interview_list
    c["offers"] = [dict(o) for o in offers]
    c["documents"] = [dict(d) for d in docs]
    # Every application this person has — the top-level stage/requisition
    # fields above (_candidate_with_derived_fields) only resolve when
    # there's exactly one; the Applications section in Candidate Detail
    # (static/js/recruitment.js) is what actually renders all of them.
    apps = conn.execute("""
        SELECT cr.*, r.title AS requisition_title FROM candidate_requisitions cr
        LEFT JOIN job_requisitions r ON r.id = cr.requisition_id
        WHERE cr.candidate_id=? AND cr.institution_id=? ORDER BY cr.created_at
    """, (cand_id, inst_id)).fetchall()
    c["applications"] = [dict(a) for a in apps]
    return c


@router.patch("/api/recruitment/candidates/{cand_id}/requisitions/{requisition_id}/stage")
@db_session
def move_application_stage(conn, cand_id: int, requisition_id: int, body: CandidateStageIn,
                            user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Explicit per-application stage move — the endpoint move_stage's own
    400 (candidate has more than one application) points callers at. Pass
    requisition_id=0 in the URL for the "general interest" (NULL) application
    — a path param can't itself carry NULL."""
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    if body.stage not in CANDIDATE_STAGES:
        raise HTTPException(400, f"Stage must be one of: {', '.join(CANDIDATE_STAGES)}")
    inst_id = need_inst(user)
    _get_candidate(conn, inst_id, cand_id)
    req_id = None if requisition_id == 0 else requisition_id
    app = conn.execute(
        "SELECT * FROM candidate_requisitions WHERE candidate_id=? AND requisition_id IS NOT DISTINCT FROM ? AND institution_id=?",
        (cand_id, req_id, inst_id)
    ).fetchone()
    if not app:
        raise HTTPException(404, "This candidate has no application for that requisition")
    old_stage = app["stage"]
    if body.stage != old_stage:
        _transition_candidate_stage(conn, inst_id, cand_id, req_id, body.stage)
    if body.notes:
        extra_notes = f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Stage moved to {body.stage} by {user['username']}: {body.notes}".strip()
        conn.execute(
            "UPDATE candidate_requisitions SET notes=COALESCE(notes,'') || ? WHERE id=?",
            (extra_notes, app["id"])
        )
    detail = f"Stage changed: {old_stage} → {body.stage}" + (f" for requisition #{req_id}" if req_id else " (general interest)")
    if body.notes: detail += f" | Reason: {body.notes}"
    _log_candidate(conn, inst_id, cand_id, "Stage Changed", detail, user["username"])
    conn.commit()
    row = conn.execute("SELECT * FROM candidate_requisitions WHERE id=?", (app["id"],)).fetchone()
    return dict(row)


@router.get("/api/recruitment/candidates/{cand_id}/documents")
@db_session
def list_candidate_documents(conn, cand_id: int, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    _get_candidate(conn, inst_id, cand_id)
    rows = conn.execute(
        "SELECT id,file_name,mime_type,data_url,uploaded_by,created_at FROM candidate_documents WHERE candidate_id=? AND institution_id=? ORDER BY created_at",
        (cand_id, inst_id)
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/recruitment/candidates/{cand_id}/documents", status_code=201)
@db_session
def add_candidate_documents(conn, cand_id: int, body: List[CandidateDocumentIn],
                             user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    inst_id = need_inst(user)
    c = _get_candidate(conn, inst_id, cand_id)
    if not body:
        raise HTTPException(400, "No files provided")
    for doc in body:
        conn.execute(
            "INSERT INTO candidate_documents (institution_id,candidate_id,file_name,mime_type,data_url,uploaded_by) VALUES (?,?,?,?,?,?)",
            (inst_id, cand_id, doc.file_name, doc.mime_type, doc.data_url, user["username"])
        )
    _log_candidate(conn, inst_id, cand_id, "Updated",
                    f"{len(body)} document(s) uploaded: {', '.join(d.file_name for d in body)}", user["username"])
    conn.commit()
    rows = conn.execute(
        "SELECT id,file_name,mime_type,data_url,uploaded_by,created_at FROM candidate_documents WHERE candidate_id=? AND institution_id=? ORDER BY created_at",
        (cand_id, inst_id)
    ).fetchall()
    return [dict(r) for r in rows]


@router.delete("/api/recruitment/candidates/{cand_id}/documents/{doc_id}", status_code=204)
@db_session
def delete_candidate_document(conn, cand_id: int, doc_id: int,
                               user: dict = Depends(get_current_user)):
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    inst_id = need_inst(user)
    _get_candidate(conn, inst_id, cand_id)
    doc = conn.execute(
        "SELECT file_name FROM candidate_documents WHERE id=? AND candidate_id=? AND institution_id=?",
        (doc_id, cand_id, inst_id)
    ).fetchone()
    if not doc:
        raise HTTPException(404, "Document not found")
    conn.execute("DELETE FROM candidate_documents WHERE id=? AND institution_id=?", (doc_id, inst_id))
    _log_candidate(conn, inst_id, cand_id, "Updated", f"Document removed: {doc['file_name']}", user["username"])
    conn.commit()


@router.put("/api/recruitment/candidates/{cand_id}")
@db_session
def update_candidate(conn, cand_id: int, body: CandidateIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    inst_id = need_inst(user)
    _get_candidate(conn, inst_id, cand_id)
    conn.execute("""
        UPDATE candidates SET full_name=?,email=?,phone=?,ic_number=?,
            nationality=?,gender=?,date_of_birth=?,address=?,current_position=?,current_company=?,
            experience_years=?,employment_history=?,highest_qualification=?,field_of_study=?,
            institution_name=?,graduation_year=?,certifications=?,skills=?,resume_text=?,
            linkedin_url=?
        WHERE id=? AND institution_id=?
    """, (body.full_name, body.email, body.phone, body.ic_number,
          body.nationality, body.gender, body.date_of_birth, body.address,
          body.current_position, body.current_company, body.experience_years, body.employment_history,
          body.highest_qualification, body.field_of_study, body.institution_name, body.graduation_year,
          body.certifications, body.skills, body.resume_text, body.linkedin_url,
          cand_id, inst_id))
    # Application-level fields (requisition/source/notes/salary/notice/
    # referral) only live on candidate_requisitions now — only writable
    # here when this is still the candidate's sole application, matched by
    # row id since body.requisition_id may itself be the field being
    # changed. Once a second application exists, this form simply can't
    # edit application-level data (no single row to target) — the
    # Applications section in Candidate Detail is where that happens.
    apps = conn.execute(
        "SELECT id FROM candidate_requisitions WHERE candidate_id=? AND institution_id=?",
        (cand_id, inst_id)
    ).fetchall()
    if len(apps) == 1:
        conn.execute("""
            UPDATE candidate_requisitions SET requisition_id=?,source=?,notes=?,
                expected_salary=?,notice_period=?,referral_by=?
            WHERE id=?
        """, (body.requisition_id, body.source, body.notes, body.expected_salary,
              body.notice_period, body.referral_by, apps[0]["id"]))
    _log_candidate(conn, inst_id, cand_id, "Updated", "Candidate profile details updated", user["username"])
    conn.commit()
    return _candidate_with_derived_fields(conn, inst_id, cand_id)


@router.patch("/api/recruitment/candidates/{cand_id}/stage")
@db_session
def move_stage(conn, cand_id: int, body: CandidateStageIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    if body.stage not in CANDIDATE_STAGES:
        raise HTTPException(400, f"Stage must be one of: {', '.join(CANDIDATE_STAGES)}")
    inst_id = need_inst(user)
    old = _candidate_with_derived_fields(conn, inst_id, cand_id)
    apps = conn.execute(
        "SELECT id, requisition_id FROM candidate_requisitions WHERE candidate_id=? AND institution_id=?",
        (cand_id, inst_id)
    ).fetchall()
    if len(apps) > 1:
        raise HTTPException(400, "This candidate has more than one application — move the stage on the "
                             "specific requisition instead (PATCH .../requisitions/{requisition_id}/stage)")
    extra_notes = f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Stage moved to {body.stage} by {user['username']}: {body.notes or ''}".strip()
    if apps:
        # The free-text annotation used to land on candidates.notes
        # (person-level) — now the sole application's own notes, since
        # that column no longer exists on candidates.
        conn.execute("UPDATE candidate_requisitions SET notes=COALESCE(notes,'') || ? WHERE id=?",
                     (extra_notes, apps[0]["id"]))
    requisition_id = apps[0]["requisition_id"] if apps else None
    if body.stage != old.get("stage"):
        _transition_candidate_stage(conn, inst_id, cand_id, requisition_id, body.stage)
    detail = f"Stage changed: {old.get('stage') or '?'} → {body.stage}"
    if body.notes: detail += f" | Reason: {body.notes}"
    _log_candidate(conn, inst_id, cand_id, "Stage Changed", detail, user["username"])
    conn.commit()
    return _candidate_with_derived_fields(conn, inst_id, cand_id)


# ---------------------------------------------------------------------------
# Recruitment — Interviews
# ---------------------------------------------------------------------------
@router.get("/api/recruitment/interviews")
@db_session
def list_interviews(conn, 
    candidate_id: Optional[int] = None,
    status: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    require_permission(conn, user, "recruitment.view_requisitions_candidates_interviews_offers")
    inst_id = need_inst(user)
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
    return [dict(r) for r in rows]


@router.post("/api/recruitment/interviews", status_code=201)
@db_session
def schedule_interview(conn, body: InterviewIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    inst_id = need_inst(user)
    _get_candidate(conn, inst_id, body.candidate_id)
    # The Interview modal has no requisition picker of its own (see #intModal
    # in static/index.html) — resolve it from the candidate's own sole
    # application instead, so the interview (and the stage transition below)
    # tie to the real requisition rather than silently landing on "general
    # interest"/NULL for the overwhelmingly common single-application case.
    req_id = body.requisition_id
    if req_id is None:
        req_id = _sole_application_requisition_id(conn, inst_id, body.candidate_id)
    conn.execute("""
        INSERT INTO interviews (institution_id,candidate_id,requisition_id,interview_type,
            scheduled_date,scheduled_time,duration_mins,location,interviewers,notes,created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (inst_id, body.candidate_id, req_id, body.interview_type,
          body.scheduled_date, body.scheduled_time, body.duration_mins,
          body.location, body.interviewers, body.notes, user["username"]))
    iid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Auto-move candidate to Interview stage
    app = conn.execute(
        "SELECT stage FROM candidate_requisitions WHERE candidate_id=? AND requisition_id IS NOT DISTINCT FROM ? AND institution_id=?",
        (body.candidate_id, req_id, inst_id)
    ).fetchone()
    if app and app["stage"] in ("New", "Screening"):
        _transition_candidate_stage(conn, inst_id, body.candidate_id, req_id, "Interview")
    _log_candidate(conn, inst_id, body.candidate_id, "Interview Scheduled",
        f"{body.interview_type} interview on {body.scheduled_date} at {body.scheduled_time}"
        + (f" with {body.interviewers}" if body.interviewers else ""),
        user["username"])
    conn.commit()
    row = conn.execute("""
        SELECT i.*, c.full_name AS candidate_name FROM interviews i
        JOIN candidates c ON c.id = i.candidate_id WHERE i.id=?
    """, (iid,)).fetchone()
    return dict(row)


@router.put("/api/recruitment/interviews/{int_id}")
@db_session
def update_interview(conn, int_id: int, body: InterviewIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    inst_id = need_inst(user)
    old_int = conn.execute("SELECT * FROM interviews WHERE id=? AND institution_id=?", (int_id, inst_id)).fetchone()
    if not old_int:
        raise HTTPException(404, "Interview not found")
    conn.execute("""
        UPDATE interviews SET interview_type=?,scheduled_date=?,scheduled_time=?,
            duration_mins=?,location=?,interviewers=?,notes=?
        WHERE id=? AND institution_id=?
    """, (body.interview_type, body.scheduled_date, body.scheduled_time,
          body.duration_mins, body.location, body.interviewers, body.notes, int_id, inst_id))
    row = conn.execute("SELECT * FROM interviews WHERE id=?", (int_id,)).fetchone()
    changes = diff_rows(old_int, row)
    if changes:
        _log_candidate(conn, inst_id, old_int["candidate_id"], "Interview Updated",
                       "; ".join(f"{c['label']}: {c['old'] or '—'} → {c['new'] or '—'}" for c in changes)[:400],
                       user["username"])
    conn.commit()
    return dict(row)


@router.patch("/api/recruitment/interviews/{int_id}/status")
@db_session
def update_interview_status(conn, int_id: int, body: InterviewStatusIn,
                             user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    if body.status not in INTERVIEW_STATUSES:
        raise HTTPException(400, f"Status must be one of: {', '.join(INTERVIEW_STATUSES)}")
    inst_id = need_inst(user)
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
    return dict(row)


@router.post("/api/recruitment/interviews/{int_id}/scores", status_code=201)
@db_session
def submit_score(conn, int_id: int, body: ScoreIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM interviews WHERE id=? AND institution_id=?", (int_id, inst_id)).fetchone():
        raise HTTPException(404, "Interview not found")
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
        _log_candidate(conn, inst_id, cand_row["candidate_id"], "Interview Scored",
                       f"Score by {user['username']}: overall {body.overall_score}, recommendation {body.recommendation}",
                       user["username"])
        conn.commit()
    except IntegrityError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.get("/api/recruitment/interviews/{int_id}/scores")
@db_session
def get_scores(conn, int_id: int, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    rows = conn.execute(
        "SELECT * FROM interview_scores WHERE interview_id=? AND institution_id=? ORDER BY created_at",
        (int_id, inst_id)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Recruitment — Offers
# ---------------------------------------------------------------------------
@router.get("/api/recruitment/offers")
@db_session
def list_offers(conn, 
    candidate_id: Optional[int] = None,
    offer_type: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    require_permission(conn, user, "recruitment.view_requisitions_candidates_interviews_offers")
    inst_id = need_inst(user)
    # candidate_id/employee_id are mutually exclusive per row (see
    # offers.employee_id's migration) — LEFT JOIN both and coalesce a
    # display name/designation so Confirmation letters (employee_id set,
    # no candidate/requisition) render in the same list as Offer/Decline
    # letters (candidate_id set) rather than needing a separate screen.
    q = """SELECT o.*,
                  COALESCE(c.full_name, e.full_name) AS recipient_name,
                  COALESCE(r.title, e.designation) AS recipient_role,
                  c.full_name AS candidate_name, r.title AS requisition_title
           FROM offers o
           LEFT JOIN candidates c ON c.id = o.candidate_id
           LEFT JOIN employees e ON e.employee_id = o.employee_id AND e.institution_id = o.institution_id
           LEFT JOIN job_requisitions r ON r.id = o.requisition_id
           WHERE o.institution_id=?"""
    p = [inst_id]
    if candidate_id: q += " AND o.candidate_id=?"; p.append(candidate_id)
    if offer_type:   q += " AND o.offer_type=?";  p.append(offer_type)
    q += " ORDER BY o.created_at DESC"
    rows = conn.execute(q, p).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/recruitment/offers", status_code=201)
@db_session
def create_offer(conn, body: OfferIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    inst_id = need_inst(user)
    if body.offer_type not in OFFER_TYPES:
        raise HTTPException(400, f"offer_type must be one of: {', '.join(OFFER_TYPES)}")

    cand, req, emp, req_id = None, None, None, body.requisition_id
    if body.offer_type == "Confirmation":
        if not body.employee_id:
            raise HTTPException(400, "employee_id is required for a Confirmation letter")
        emp = _get_employee_for_letter(conn, inst_id, body.employee_id)
    else:
        if not body.candidate_id:
            raise HTTPException(400, "candidate_id is required")
        cand = _get_candidate(conn, inst_id, body.candidate_id)
        # offerReqId defaults to blank in the UI — fall back to the
        # candidate's own sole application when HR leaves it unset, same
        # resolution schedule_interview uses for its own requisition-less form.
        req_id = body.requisition_id
        if req_id is None:
            req_id = _sole_application_requisition_id(conn, inst_id, body.candidate_id)
        if req_id:
            r = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (req_id,)).fetchone()
            req = dict(r) if r else None

    # Auto-generate letter if not provided, from the requested template (or
    # this offer_type's default, created lazily if this is the first offer
    # of its type for the institution).
    if body.letter_content:
        letter = body.letter_content
    else:
        if body.template_id:
            tmpl = conn.execute(
                "SELECT * FROM offer_letter_templates WHERE id=? AND institution_id=? AND offer_type=?",
                (body.template_id, inst_id, body.offer_type)
            ).fetchone()
            if not tmpl:
                raise HTTPException(404, "Template not found")
            tmpl = dict(tmpl)
        else:
            tmpl = _get_or_create_default_offer_template(conn, inst_id, body.offer_type)
        letter = _render_offer_letter(tmpl["body"], cand, req, body.model_dump(), emp)
    conn.execute("""
        INSERT INTO offers (institution_id,candidate_id,employee_id,requisition_id,offer_type,
            salary_offered,start_date,expiry_date,letter_content,created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (inst_id, body.candidate_id, body.employee_id, req_id, body.offer_type,
          body.salary_offered, body.start_date, body.expiry_date, letter, user["username"]))
    oid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    if cand:
        # Move candidate stage. A "Decline" letter is HR sending a regret
        # letter (company-initiated), so it maps to Rejected by Company —
        # distinct from a candidate declining/withdrawing themselves.
        new_stage = "Offer" if body.offer_type == "Offer" else "Rejected by Company"
        _transition_candidate_stage(conn, inst_id, body.candidate_id, req_id, new_stage)
        sal = f"RM {body.salary_offered:,.0f}" if body.salary_offered else "—"
        _log_candidate(conn, inst_id, body.candidate_id, f"{body.offer_type} Letter Generated",
            f"{body.offer_type} letter created" + (f" | Salary: {sal}" if body.offer_type == "Offer" else ""),
            user["username"])
    else:
        # Confirmation: no candidate stage to move — logged against the
        # employee's own record instead (see _log_employee_note).
        _log_employee_note(conn, inst_id, body.employee_id,
            "Confirmation letter generated (probation passed).", user["username"])
    conn.commit()
    row = conn.execute("SELECT * FROM offers WHERE id=?", (oid,)).fetchone()
    return dict(row)


@router.get("/api/recruitment/offers/{offer_id}")
@db_session
def get_offer(conn, offer_id: int, user: dict = Depends(get_current_user)) -> Optional[Dict[str, Any]]:
    require_permission(conn, user, "recruitment.view_requisitions_candidates_interviews_offers")
    inst_id = need_inst(user)
    row = conn.execute("""
        SELECT o.*, COALESCE(c.full_name, e.full_name) AS candidate_name
        FROM offers o
        LEFT JOIN candidates c ON c.id = o.candidate_id
        LEFT JOIN employees e ON e.employee_id = o.employee_id AND e.institution_id = o.institution_id
        WHERE o.id=? AND o.institution_id=?
    """, (offer_id, inst_id)).fetchone()
    if not row: raise HTTPException(404, "Offer not found")
    return dict(row)


@router.delete("/api/recruitment/offers/{offer_id}", status_code=204)
@db_session
def delete_offer(conn, offer_id: int, user: dict = Depends(get_current_user)) -> None:
    require_permission(conn, user, "recruitment.delete_offer_letter")
    inst_id = need_inst(user)
    row = conn.execute("SELECT * FROM offers WHERE id=? AND institution_id=?", (offer_id, inst_id)).fetchone()
    if not row:
        raise HTTPException(404, "Offer not found")
    # Accepted is a finalized, legally-significant outcome (the candidate's
    # signed acceptance) — deletable statuses are everything before or
    # instead of that (Draft/Sent/Rejected/Withdrawn). Doesn't touch the
    # candidate's stage either way; this is record cleanup, not an
    # undo of whatever stage transition creating it caused.
    if row["status"] == "Accepted":
        raise HTTPException(400, "Cannot delete an accepted offer — it's a finalized record.")
    conn.execute("DELETE FROM offers WHERE id=?", (offer_id,))
    detail = f"{row['offer_type']} letter deleted (was {row['status']})"
    if row["candidate_id"]:
        _log_candidate(conn, inst_id, row["candidate_id"], "Offer Deleted", detail, user["username"])
    else:
        _log_employee_note(conn, inst_id, row["employee_id"], detail, user["username"])
    conn.commit()


@router.patch("/api/recruitment/offers/{offer_id}/status")
@db_session
def update_offer_status(conn, offer_id: int, body: OfferStatusIn,
                         user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    if body.status not in OFFER_STATUSES:
        raise HTTPException(400, f"Status must be one of: {', '.join(OFFER_STATUSES)}")
    inst_id = need_inst(user)
    row = conn.execute("SELECT * FROM offers WHERE id=? AND institution_id=?", (offer_id, inst_id)).fetchone()
    if not row: raise HTTPException(404, "Offer not found")
    conn.execute("UPDATE offers SET status=? WHERE id=?", (body.status, offer_id))
    # Sync candidate stage
    if body.status == "Accepted" and row["offer_type"] == "Offer":
        app_row = conn.execute(
            "SELECT stage FROM candidate_requisitions WHERE candidate_id=? AND requisition_id IS NOT DISTINCT FROM ? AND institution_id=?",
            (row["candidate_id"], row["requisition_id"], inst_id)
        ).fetchone()
        if app_row and app_row["stage"] != "Offer":
            _transition_candidate_stage(conn, inst_id, row["candidate_id"], row["requisition_id"], "Offer")
    detail = f"{row['offer_type']} letter status changed to '{body.status}'"
    if row["candidate_id"]:
        _log_candidate(conn, inst_id, row["candidate_id"], "Offer Status Updated", detail, user["username"])
    else:
        _log_employee_note(conn, inst_id, row["employee_id"], detail, user["username"])
    conn.commit()
    return {"ok": True, "status": body.status}


@router.post("/api/recruitment/offers/{offer_id}/generate-letter")
@db_session
def generate_letter(conn, offer_id: int, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    """Regenerate/preview offer letter text."""
    inst_id = need_inst(user)
    row = conn.execute("SELECT * FROM offers WHERE id=? AND institution_id=?", (offer_id, inst_id)).fetchone()
    if not row: raise HTTPException(404, "Offer not found")
    offer = dict(row)
    cand, req, emp = None, None, None
    if offer.get("employee_id"):
        emp = _get_employee_for_letter(conn, inst_id, offer["employee_id"])
    else:
        cand = _get_candidate(conn, inst_id, offer["candidate_id"])
        if offer.get("requisition_id"):
            r = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (offer["requisition_id"],)).fetchone()
            req = dict(r) if r else None
    tmpl = _get_or_create_default_offer_template(conn, inst_id, offer["offer_type"])
    letter = _render_offer_letter(tmpl["body"], cand, req, offer, emp)
    conn.execute("UPDATE offers SET letter_content=? WHERE id=?", (letter, offer_id))
    conn.commit()
    return {"letter_content": letter}


# ---------------------------------------------------------------------------
# Recruitment — Offer Letter Templates
# ---------------------------------------------------------------------------
@router.get("/api/recruitment/offer-letter-templates")
@db_session
def list_offer_letter_templates(conn, offer_type: Optional[str] = None,
                                 user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    require_permission(conn, user, "recruitment.manage_offer_letter_templates")
    inst_id = need_inst(user)
    q = "SELECT * FROM offer_letter_templates WHERE institution_id=?"
    p: list = [inst_id]
    if offer_type:
        q += " AND offer_type=?"; p.append(offer_type)
    q += " ORDER BY offer_type, is_default DESC, name"
    rows = conn.execute(q, p).fetchall()
    return [dict(r) for r in rows]


def _validate_offer_letter_template(body: OfferLetterTemplateIn):
    if body.offer_type not in OFFER_TYPES:
        raise HTTPException(400, f"offer_type must be one of: {', '.join(OFFER_TYPES)}")
    if not body.name.strip():
        raise HTTPException(400, "name is required")
    if not body.body.strip():
        raise HTTPException(400, "body is required")


@router.post("/api/recruitment/offer-letter-templates", status_code=201)
@db_session
def create_offer_letter_template(conn, body: OfferLetterTemplateIn,
                                  user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.manage_offer_letter_templates")
    _validate_offer_letter_template(body)
    inst_id = need_inst(user)
    if body.is_default:
        conn.execute("UPDATE offer_letter_templates SET is_default=0 WHERE institution_id=? AND offer_type=?",
                     (inst_id, body.offer_type))
    conn.execute(
        "INSERT INTO offer_letter_templates (institution_id,offer_type,name,body,is_default) VALUES (?,?,?,?,?)",
        (inst_id, body.offer_type, body.name.strip(), body.body, 1 if body.is_default else 0)
    )
    tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    write_entity_audit(conn, user, inst_id, "Recruitment", "offer_template", tid, "Created",
                       detail=f"{body.offer_type} offer letter template '{body.name.strip()}' created"
                              + (" (default)" if body.is_default else ""), entity_label=body.name.strip())
    conn.commit()
    return dict(conn.execute("SELECT * FROM offer_letter_templates WHERE id=?", (tid,)).fetchone())


@router.put("/api/recruitment/offer-letter-templates/{tmpl_id}")
@db_session
def update_offer_letter_template(conn, tmpl_id: int, body: OfferLetterTemplateIn,
                                  user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.manage_offer_letter_templates")
    _validate_offer_letter_template(body)
    inst_id = need_inst(user)
    tmpl = conn.execute("SELECT * FROM offer_letter_templates WHERE id=? AND institution_id=?",
                         (tmpl_id, inst_id)).fetchone()
    if not tmpl:
        raise HTTPException(404, "Template not found")
    if body.is_default:
        conn.execute("UPDATE offer_letter_templates SET is_default=0 WHERE institution_id=? AND offer_type=? AND id<>?",
                     (inst_id, body.offer_type, tmpl_id))
    conn.execute(
        "UPDATE offer_letter_templates SET offer_type=?,name=?,body=?,is_default=?,"
        "updated_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=?",
        (body.offer_type, body.name.strip(), body.body, 1 if body.is_default else 0, tmpl_id)
    )
    new_tmpl = conn.execute("SELECT * FROM offer_letter_templates WHERE id=?", (tmpl_id,)).fetchone()
    changes = diff_rows(tmpl, new_tmpl, exclude=("body",))
    if tmpl["body"] != new_tmpl["body"]:
        changes.append({"field": "body", "label": "Letter body", "old": "(previous text)", "new": "(edited)"})
    if changes:
        write_entity_audit(conn, user, inst_id, "Recruitment", "offer_template", tmpl_id, "Updated", changes=changes, entity_label=new_tmpl["name"])
    conn.commit()
    return dict(new_tmpl)


@router.delete("/api/recruitment/offer-letter-templates/{tmpl_id}", status_code=204)
@db_session
def delete_offer_letter_template(conn, tmpl_id: int, user: dict = Depends(get_current_user)) -> None:
    require_permission(conn, user, "recruitment.manage_offer_letter_templates")
    inst_id = need_inst(user)
    tmpl = conn.execute("SELECT * FROM offer_letter_templates WHERE id=? AND institution_id=?",
                         (tmpl_id, inst_id)).fetchone()
    if not tmpl:
        raise HTTPException(404, "Template not found")
    conn.execute("DELETE FROM offer_letter_templates WHERE id=?", (tmpl_id,))
    # Promote another template of the same type to default, if one exists,
    # so _get_or_create_default_offer_template's ORDER BY is_default DESC
    # still resolves to something sensible rather than an arbitrary row.
    if tmpl["is_default"]:
        other = conn.execute(
            "SELECT id FROM offer_letter_templates WHERE institution_id=? AND offer_type=? AND id<>? ORDER BY id LIMIT 1",
            (inst_id, tmpl["offer_type"], tmpl_id)
        ).fetchone()
        if other:
            conn.execute("UPDATE offer_letter_templates SET is_default=1 WHERE id=?", (other["id"],))
    write_entity_audit(conn, user, inst_id, "Recruitment", "offer_template", tmpl_id, "Deleted",
                       detail=f"{tmpl['offer_type']} offer letter template '{tmpl['name']}' deleted", entity_label=tmpl["name"])
    conn.commit()


@router.get("/api/recruitment/candidates/{cand_id}/convert-prefill")
@db_session
def convert_to_employee_prefill(conn, cand_id: int, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "recruitment.create_edit_requisition_candidate_interview_offer")
    """Return candidate data pre-formatted for the Add Employee form."""
    inst_id = need_inst(user)
    c = _get_candidate(conn, inst_id, cand_id)
    # Get accepted offer for salary/start date
    offer = conn.execute(
        "SELECT * FROM offers WHERE candidate_id=? AND offer_type='Offer' AND status='Accepted' ORDER BY created_at DESC LIMIT 1",
        (cand_id,)
    ).fetchone()
    # The accepted offer's own requisition_id is the authoritative answer —
    # it's what the candidate was actually hired for — falling back to the
    # candidate's sole application only if that offer somehow has none.
    req_id = (offer["requisition_id"] if offer else None) or _sole_application_requisition_id(conn, inst_id, cand_id)
    req = None
    if req_id:
        r = conn.execute("SELECT * FROM job_requisitions WHERE id=?", (req_id,)).fetchone()
        req = dict(r) if r else None
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


@router.get("/api/recruitment/meta")
@db_session
def recruitment_meta(conn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
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


@router.get("/api/recruitment/candidates/{cand_id}/audit-log")
@db_session
def get_candidate_audit(conn, cand_id: int, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    require_permission(conn, user, "recruitment.view_candidate_audit_log")
    inst_id = need_inst(user)
    _get_candidate(conn, inst_id, cand_id)
    rows = conn.execute(
        "SELECT * FROM candidate_audit_log WHERE candidate_id=? AND institution_id=? ORDER BY created_at DESC",
        (cand_id, inst_id)
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/recruitment/candidates/{cand_id}/stage-history")
@db_session
def get_candidate_stage_history(conn, cand_id: int, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    require_permission(conn, user, "recruitment.view_candidate_stage_timing")
    inst_id = need_inst(user)
    _get_candidate(conn, inst_id, cand_id)
    rows = conn.execute("""
        SELECT *, EXTRACT(EPOCH FROM (
            COALESCE(exited_at::timestamp, NOW() AT TIME ZONE 'UTC') - entered_at::timestamp
        ))::int AS duration_seconds
        FROM candidate_stage_history WHERE candidate_id=? AND institution_id=? ORDER BY entered_at ASC
    """, (cand_id, inst_id)).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/recruitment/dashboard-stats")
@db_session
def recruitment_dashboard_stats(conn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    iid = need_inst(user)
    # Requisitions by status
    req_rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM job_requisitions WHERE institution_id=? GROUP BY status", (iid,)
    ).fetchall()
    req_by_status = {r["status"]: r["cnt"] for r in req_rows}

    # Candidates by stage — counts applications (candidate_requisitions),
    # not unique people: today that's the same number (one row per person),
    # but stays correct once a person can have more than one application.
    cand_rows = conn.execute(
        "SELECT stage, COUNT(*) as cnt FROM candidate_requisitions WHERE institution_id=? GROUP BY stage", (iid,)
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
        "SELECT COUNT(*) FROM candidate_requisitions WHERE institution_id=? AND stage='Hired' AND LEFT(updated_at,7)=to_char(NOW(),'YYYY-MM')",
        (iid,)
    ).fetchone()[0]

    # Average time spent per stage — blends completed stays (exited_at
    # set) with candidates still currently in that stage (exited_at
    # NULL, using NOW() as the still-running end point), per design.
    stage_time_rows = conn.execute("""
        SELECT stage, AVG(EXTRACT(EPOCH FROM (
            COALESCE(exited_at::timestamp, NOW() AT TIME ZONE 'UTC') - entered_at::timestamp
        )))::int AS avg_seconds
        FROM candidate_stage_history WHERE institution_id=? GROUP BY stage
    """, (iid,)).fetchall()
    avg_time_in_stage = {r["stage"]: r["avg_seconds"] for r in stage_time_rows}

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
        "avg_time_in_stage": avg_time_in_stage,
    }
