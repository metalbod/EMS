"""Recruitment module: Job Requisitions, Candidates/ATS, Interviews, and Offers."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from core.deps import get_current_user, need_inst, require_roles
except ImportError:
    from ems.core.deps import get_current_user, need_inst, require_roles

try:
    from db import get_db, IntegrityError
except ImportError:
    from ems.db import get_db, IntegrityError

router = APIRouter()

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

RECRUIT_WRITE = ("superadmin", "hr_manager", "hr_admin")


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


def _log_candidate(conn, inst_id: int, cand_id: int, action: str, detail: str, by: str):
    conn.execute(
        "INSERT INTO candidate_audit_log (institution_id,candidate_id,action,detail,performed_by) VALUES (?,?,?,?,?)",
        (inst_id, cand_id, action, detail, by)
    )


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
@router.get("/api/recruitment/requisitions")
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


@router.post("/api/recruitment/requisitions", status_code=201)
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


@router.get("/api/recruitment/requisitions/{req_id}")
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


@router.put("/api/recruitment/requisitions/{req_id}")
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


@router.patch("/api/recruitment/requisitions/{req_id}/submit")
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


@router.patch("/api/recruitment/requisitions/{req_id}/approve")
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


@router.patch("/api/recruitment/requisitions/{req_id}/close")
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
@router.get("/api/recruitment/candidates")
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


@router.post("/api/recruitment/candidates", status_code=201)
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


@router.get("/api/recruitment/candidates/{cand_id}")
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


@router.put("/api/recruitment/candidates/{cand_id}")
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


@router.patch("/api/recruitment/candidates/{cand_id}/stage")
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
@router.get("/api/recruitment/interviews")
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


@router.post("/api/recruitment/interviews", status_code=201)
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


@router.put("/api/recruitment/interviews/{int_id}")
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


@router.patch("/api/recruitment/interviews/{int_id}/status")
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


@router.post("/api/recruitment/interviews/{int_id}/scores", status_code=201)
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


@router.get("/api/recruitment/interviews/{int_id}/scores")
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
@router.get("/api/recruitment/offers")
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


@router.post("/api/recruitment/offers", status_code=201)
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


@router.get("/api/recruitment/offers/{offer_id}")
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


@router.patch("/api/recruitment/offers/{offer_id}/status")
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


@router.post("/api/recruitment/offers/{offer_id}/generate-letter")
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


@router.get("/api/recruitment/candidates/{cand_id}/convert-prefill")
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


@router.get("/api/recruitment/meta")
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


@router.get("/api/recruitment/candidates/{cand_id}/audit-log")
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


@router.get("/api/recruitment/dashboard-stats")
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
