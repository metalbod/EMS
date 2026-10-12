"""Policy acknowledgements — HR publishes a document (employee handbook, memo, code of conduct),
assigns it to an audience, and each person opens it and acknowledges it. See
migrations/versions/20261013_0001_policy_acknowledgements.py and core/policies.py.

A policy is an ld_courses row with category 'policy' (so it appears in the L&D Course Catalog under
the Policies filter); each version is a policy_versions row; each assigned person has one
policy_acknowledgements row per version. Publishing a new version asks its audience again — earlier
versions and who acknowledged them are kept.

Deliberately: assignment is explicit (people who join later are NOT added automatically — HR uses
"Add people" on the tracker, or links the policy to an onboarding checklist item); acknowledging
is a tick box recorded with the account, time and exact wording, not a signature.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import os
import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from core.audit import write_entity_audit
from core.db_session import db_session
from core.deps import get_current_user, need_inst
from core.email_engine import _cooldown_cutoff, _smtp_settings, queue_email
from core.ob_ld_shared import complete_linked_ob_items
from core.org_queries import subordinates_in_clause
from core.permission_matrix import has_permission, require_permission
from core.policies import (
    AUDIENCE_TYPES, MANUAL_REMIND_COOLDOWN_DAYS, POLICY_CATEGORY, REMINDER_CATEGORY, ack_status, assign_version,
    csv_cell, current_version, last_reminded_map, reminder_dedupe_key, reminder_email, resolve_audience,
    today_for_institution,
)
from routers.ld import validate_document_upload

router = APIRouter()

MANAGE_KEY = "learning_development.manage_courses_quizzes"
# HR/managers may open any policy's document; everyone else only one assigned to them.
FILE_ANY_ROLES = ("superadmin", "hr_manager", "hr_admin", "manager")


class PolicyPublishIn(BaseModel):
    title: Optional[str] = None            # required for a new policy; optional rename for a new version
    description: Optional[str] = None
    change_note: Optional[str] = None
    due_date: Optional[str] = None         # YYYY-MM-DD
    require_open: bool = True
    audience_type: str = "all"             # all | department | team | people
    audience_ref: Optional[str] = None     # department name, or the team lead's employee_id
    employee_ids: List[str] = []           # for audience_type 'people'
    file_name: str
    data_url: str


class PolicyAssignIn(BaseModel):
    employee_ids: List[str]


class PolicyAcknowledgeIn(BaseModel):
    confirm: bool = False


def _check_audience(conn, inst_id: int, body: PolicyPublishIn) -> List[str]:
    if body.audience_type not in AUDIENCE_TYPES:
        raise HTTPException(400, f"audience_type must be one of: {', '.join(AUDIENCE_TYPES)}")
    if body.audience_type == "department" and not (body.audience_ref or "").strip():
        raise HTTPException(400, "Choose a department")
    if body.audience_type == "team":
        if not body.audience_ref or not conn.execute(
            "SELECT 1 FROM employees WHERE employee_id=? AND institution_id=?", (body.audience_ref, inst_id)
        ).fetchone():
            raise HTTPException(400, "Choose the manager whose team should acknowledge it")
    if body.audience_type == "people" and not body.employee_ids:
        raise HTTPException(400, "Choose at least one person")
    ids = resolve_audience(conn, inst_id, body.audience_type, body.audience_ref, body.employee_ids)
    if not ids:
        raise HTTPException(400, "No active employees match that audience")
    return ids


def _check_due_date(due: Optional[str]) -> Optional[str]:
    if not due:
        return None
    try:
        datetime.strptime(due, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Acknowledge-by date must be a valid date")
    return due


def _store_version(conn, inst_id: int, course_id: int, version: int, body: PolicyPublishIn,
                   user: dict, audience_ids: List[str]) -> int:
    file_name, mime, data = validate_document_upload(body.file_name, body.data_url)
    conn.execute(
        "INSERT INTO ld_module_files (institution_id,course_id,file_name,mime_type,size_bytes,data,uploaded_by) VALUES (?,?,?,?,?,?,?)",
        (inst_id, course_id, file_name, mime, len(data), psycopg2.Binary(data), user["username"])
    )
    file_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO policy_versions (institution_id,course_id,version,file_id,change_note,due_date,require_open,"
        "audience_type,audience_ref,published_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (inst_id, course_id, version, file_id, (body.change_note or "").strip() or None, _check_due_date(body.due_date),
         1 if body.require_open else 0, body.audience_type, (body.audience_ref or None), user["username"])
    )
    version_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    assign_version(conn, inst_id, version_id, audience_ids)
    return version_id


def _get_policy(conn, inst_id: int, course_id: int):
    course = conn.execute(
        "SELECT * FROM ld_courses WHERE id=? AND institution_id=? AND category=?", (course_id, inst_id, POLICY_CATEGORY)
    ).fetchone()
    if not course:
        raise HTTPException(404, "Policy not found")
    return course


def _scope(conn, inst_id: int, user: dict):
    """(sees_everyone, scope_fragment, scope_params): HR sees all; a manager only their reporting
    chain; anyone else is refused."""
    if has_permission(conn, inst_id, user, MANAGE_KEY):
        return True, "", []
    if user["role"] == "manager" and user.get("employee_id"):
        frag, fp = subordinates_in_clause(inst_id, user["employee_id"])
        return False, f" AND a.employee_id IN {frag}", fp
    raise HTTPException(403, "Only HR and managers can see acknowledgement status")


@router.post("/api/policies", status_code=201)
@db_session
def publish_policy(conn, body: PolicyPublishIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, MANAGE_KEY)
    inst_id = need_inst(user)
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(400, "Enter a title")
    ids = _check_audience(conn, inst_id, body)
    conn.execute(
        "INSERT INTO ld_courses (institution_id,title,category,description,cost,is_active,created_by) VALUES (?,?,?,?,?,?,?)",
        (inst_id, title, POLICY_CATEGORY, (body.description or "").strip() or None, 0, 1, user["username"])
    )
    course_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    version_id = _store_version(conn, inst_id, course_id, 1, body, user, ids)
    write_entity_audit(conn, user, inst_id, "L&D", "policy", course_id, "Published",
                       detail=f"Policy '{title}' v1 published to {len(ids)} employee(s) ({body.audience_type})", entity_label=title)
    conn.commit()
    return {"course_id": course_id, "version_id": version_id, "version": 1, "assigned": len(ids)}


@router.post("/api/policies/{course_id}/versions", status_code=201)
@db_session
def publish_policy_version(conn, course_id: int, body: PolicyPublishIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """A new version asks its audience to acknowledge again; earlier versions stay on record."""
    require_permission(conn, user, MANAGE_KEY)
    inst_id = need_inst(user)
    course = _get_policy(conn, inst_id, course_id)
    ids = _check_audience(conn, inst_id, body)
    prev = current_version(conn, inst_id, course_id)
    version = (prev["version"] if prev else 0) + 1
    new_title = (body.title or "").strip() or course["title"]
    if new_title != course["title"] or body.description is not None:
        conn.execute("UPDATE ld_courses SET title=?, description=COALESCE(?, description) WHERE id=?",
                     (new_title, (body.description or "").strip() or None, course_id))
    version_id = _store_version(conn, inst_id, course_id, version, body, user, ids)
    write_entity_audit(conn, user, inst_id, "L&D", "policy", course_id, "New version",
                       detail=f"Policy '{new_title}' v{version} published to {len(ids)} employee(s) ({body.audience_type})",
                       entity_label=new_title)
    conn.commit()
    return {"course_id": course_id, "version_id": version_id, "version": version, "assigned": len(ids)}


@router.get("/api/policies")
@db_session
def list_policies(conn, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Each active policy's current version with how many people have opened / acknowledged it.
    A manager sees only their own reporting chain's numbers (and only policies that reach them)."""
    inst_id = need_inst(user)
    sees_all, scope_sql, scope_params = _scope(conn, inst_id, user)
    today = today_for_institution(conn, inst_id)
    versions = conn.execute("""
        SELECT c.id AS course_id, c.title, c.description, v.id AS version_id, v.version, v.due_date, v.audience_type,
               v.audience_ref, v.require_open, v.change_note, v.created_at AS published_at, f.file_name
        FROM ld_courses c
        JOIN policy_versions v ON v.course_id=c.id
             AND v.version=(SELECT MAX(version) FROM policy_versions WHERE course_id=c.id)
        JOIN ld_module_files f ON f.id=v.file_id
        WHERE c.institution_id=? AND c.category=? AND c.is_active=1
        ORDER BY c.title
    """, (inst_id, POLICY_CATEGORY)).fetchall()
    out = []
    for v in versions:
        acks = conn.execute(
            f"SELECT a.* FROM policy_acknowledgements a WHERE a.version_id=?{scope_sql}", [v["version_id"], *scope_params]
        ).fetchall()
        if not sees_all and not acks:
            continue
        row = dict(v)
        statuses = [ack_status(a, v["due_date"], today) for a in acks]
        row.update(assigned=len(acks), opened=sum(1 for a in acks if a["first_opened_at"]),
                   acknowledged=statuses.count("acknowledged"), overdue=statuses.count("overdue"))
        out.append(row)
    return out


@router.get("/api/policies/mine")
@db_session
def my_policies(conn, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """The caller's own acknowledgements: pending ones for the current version of each policy, plus
    everything they've acknowledged (history). A pending request for a version that has since been
    replaced is hidden — the new version supersedes it."""
    inst_id = need_inst(user)
    emp_id = user.get("employee_id")
    if not emp_id:
        return []
    today = today_for_institution(conn, inst_id)
    rows = conn.execute("""
        SELECT a.id AS ack_id, a.version_id, a.assigned_at, a.first_opened_at, a.acknowledged_at,
               v.course_id, v.version, v.change_note, v.due_date, v.require_open, f.file_name,
               c.title, c.description,
               (v.version=(SELECT MAX(version) FROM policy_versions WHERE course_id=v.course_id)) AS is_current
        FROM policy_acknowledgements a
        JOIN policy_versions v ON v.id=a.version_id
        JOIN ld_courses c ON c.id=v.course_id AND c.is_active=1
        JOIN ld_module_files f ON f.id=v.file_id
        WHERE a.institution_id=? AND a.employee_id=?
        ORDER BY a.assigned_at DESC
    """, (inst_id, emp_id)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if not d["acknowledged_at"] and not d["is_current"]:
            continue
        d["status"] = ack_status(r, r["due_date"], today)
        out.append(d)
    return out


@router.get("/api/policies/{course_id}/tracker")
@db_session
def policy_tracker(conn, course_id: int, version_id: Optional[int] = None, status: Optional[str] = None,
                   user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    sees_all, scope_sql, scope_params = _scope(conn, inst_id, user)
    course = _get_policy(conn, inst_id, course_id)
    versions = [dict(v) for v in conn.execute(
        "SELECT id, version, change_note, due_date, created_at, published_by, audience_type, audience_ref, require_open "
        "FROM policy_versions WHERE course_id=? AND institution_id=? ORDER BY version DESC", (course_id, inst_id)
    ).fetchall()]
    if not versions:
        raise HTTPException(404, "This policy has no published version")
    ver = next((v for v in versions if v["id"] == version_id), versions[0]) if version_id else versions[0]
    is_current = ver["id"] == versions[0]["id"]
    today = today_for_institution(conn, inst_id)
    acks = conn.execute(
        f"""SELECT a.*, e.full_name, e.preferred_name, e.department, e.status AS employee_status
            FROM policy_acknowledgements a
            LEFT JOIN employees e ON e.employee_id=a.employee_id AND e.institution_id=a.institution_id
            WHERE a.version_id=?{scope_sql} ORDER BY e.full_name""", [ver["id"], *scope_params]
    ).fetchall()
    reminded = last_reminded_map(conn, inst_id, ver["id"])
    rows = []
    for a in acks:
        st = ack_status(a, ver["due_date"], today)
        rows.append({
            "employee_id": a["employee_id"], "full_name": a["full_name"], "preferred_name": a["preferred_name"],
            "department": a["department"], "employee_status": a["employee_status"], "status": st,
            "assigned_at": a["assigned_at"], "first_opened_at": a["first_opened_at"], "acknowledged_at": a["acknowledged_at"],
            "last_reminded_at": reminded.get(a["employee_id"]),
        })
    summary = {
        "assigned": len(rows), "opened": sum(1 for r in rows if r["first_opened_at"]),
        "acknowledged": sum(1 for r in rows if r["status"] == "acknowledged"),
        "overdue": sum(1 for r in rows if r["status"] == "overdue"),
    }
    if status == "outstanding":
        rows = [r for r in rows if r["status"] != "acknowledged"]
    elif status == "acknowledged":
        rows = [r for r in rows if r["status"] == "acknowledged"]
    unassigned = []
    if sees_all and is_current and ver["audience_type"] in ("all", "department", "team"):
        have = {a["employee_id"] for a in acks}
        for emp_id in resolve_audience(conn, inst_id, ver["audience_type"], ver["audience_ref"]):
            if emp_id not in have:
                e = conn.execute("SELECT employee_id, full_name, department FROM employees WHERE employee_id=? AND institution_id=?",
                                 (emp_id, inst_id)).fetchone()
                unassigned.append(dict(e))
    return {
        "policy": {"course_id": course_id, "title": course["title"], "description": course["description"]},
        "version": ver, "versions": versions, "is_current": is_current, "summary": summary,
        "rows": rows, "unassigned": unassigned, "can_manage": sees_all,
        "email_ready": bool(_smtp_settings(conn, inst_id)) if sees_all else None,
    }


@router.post("/api/policies/versions/{version_id}/assign")
@db_session
def assign_policy_people(conn, version_id: int, body: PolicyAssignIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """"Add people": assign the current version to more employees (e.g. people who joined after it was published)."""
    require_permission(conn, user, MANAGE_KEY)
    inst_id = need_inst(user)
    ver = conn.execute("SELECT * FROM policy_versions WHERE id=? AND institution_id=?", (version_id, inst_id)).fetchone()
    if not ver:
        raise HTTPException(404, "Policy version not found")
    latest = current_version(conn, inst_id, ver["course_id"])
    if latest["id"] != ver["id"]:
        raise HTTPException(400, "Only the current version can be assigned to more people")
    ids = resolve_audience(conn, inst_id, "people", None, body.employee_ids)
    if not ids:
        raise HTTPException(400, "No active employees to add")
    added = assign_version(conn, inst_id, version_id, ids)
    course = conn.execute("SELECT title FROM ld_courses WHERE id=?", (ver["course_id"],)).fetchone()
    write_entity_audit(conn, user, inst_id, "L&D", "policy", ver["course_id"], "People added",
                       detail=f"v{ver['version']} assigned to {added} more employee(s)", entity_label=course["title"])
    conn.commit()
    return {"added": added}


@router.get("/api/policies/versions/{version_id}/file")
@db_session
def download_policy_file(conn, version_id: int, inline: bool = False, user: dict = Depends(get_current_user)):
    """The document. Someone it's assigned to may open it (the first time is recorded as 'opened');
    HR and managers may open any policy's document."""
    inst_id = need_inst(user)
    ver = conn.execute("SELECT * FROM policy_versions WHERE id=? AND institution_id=?", (version_id, inst_id)).fetchone()
    if not ver:
        raise HTTPException(404, "File not found")
    own = None
    if user.get("employee_id"):
        own = conn.execute("SELECT id, first_opened_at FROM policy_acknowledgements WHERE version_id=? AND employee_id=?",
                           (version_id, user["employee_id"])).fetchone()
    if not own and user["role"] not in FILE_ANY_ROLES:
        raise HTTPException(403, "This policy isn't assigned to you")
    f = conn.execute("SELECT file_name, mime_type, data FROM ld_module_files WHERE id=? AND institution_id=?",
                     (ver["file_id"], inst_id)).fetchone()
    if not f:
        raise HTTPException(404, "File not found")
    if own and not own["first_opened_at"]:
        conn.execute("UPDATE policy_acknowledgements SET first_opened_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=?",
                     (own["id"],))
        conn.commit()
    disposition = "inline" if (inline and f["mime_type"] == "application/pdf") else "attachment"
    quoted = f["file_name"].replace('"', "'")
    return Response(
        content=bytes(f["data"]), media_type=f["mime_type"],
        headers={
            "Content-Disposition": f"{disposition}; filename=\"{quoted.encode('ascii', 'replace').decode()}\"; filename*=UTF-8''{quote(f['file_name'])}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        })


@router.post("/api/policies/versions/{version_id}/acknowledge")
@db_session
def acknowledge_policy(conn, version_id: int, body: PolicyAcknowledgeIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    emp_id = user.get("employee_id")
    ack = conn.execute("SELECT * FROM policy_acknowledgements WHERE version_id=? AND employee_id=? AND institution_id=?",
                       (version_id, emp_id, inst_id)).fetchone() if emp_id else None
    if not ack:
        raise HTTPException(403, "This policy isn't assigned to you")
    ver = conn.execute("SELECT * FROM policy_versions WHERE id=?", (version_id,)).fetchone()
    course = conn.execute("SELECT title FROM ld_courses WHERE id=?", (ver["course_id"],)).fetchone()
    if ack["acknowledged_at"]:
        return {"acknowledged_at": ack["acknowledged_at"], "already": True}
    latest = current_version(conn, inst_id, ver["course_id"])
    if latest["id"] != ver["id"]:
        raise HTTPException(400, "A newer version of this policy has been published. Please read that one.")
    if not body.confirm:
        raise HTTPException(400, "Tick the box to confirm you have read and understood it")
    if ver["require_open"] and not ack["first_opened_at"]:
        raise HTTPException(400, "Open the document first, then acknowledge it")
    statement = f"I have read and understood {course['title']} (v{ver['version']})."
    conn.execute(
        "UPDATE policy_acknowledgements SET acknowledged_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS'), "
        "statement=?, acknowledged_by=? WHERE id=?", (statement, user["username"], ack["id"])
    )
    complete_linked_ob_items(conn, inst_id, emp_id, ver["course_id"], user)
    write_entity_audit(conn, user, inst_id, "L&D", "policy", ver["course_id"], "Acknowledged",
                       detail=f"{emp_id} acknowledged v{ver['version']}", entity_label=course["title"])
    conn.commit()
    row = conn.execute("SELECT acknowledged_at FROM policy_acknowledgements WHERE id=?", (ack["id"],)).fetchone()
    return {"acknowledged_at": row["acknowledged_at"], "already": False}


@router.post("/api/policies/versions/{version_id}/remind")
@db_session
def remind_policy_outstanding(conn, version_id: int, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """HR's manual "Send reminder": emails everyone who still hasn't acknowledged this (current) version,
    except anyone already reminded in the last day. Goes out in the background; each send is logged."""
    require_permission(conn, user, MANAGE_KEY)
    inst_id = need_inst(user)
    ver = conn.execute("SELECT * FROM policy_versions WHERE id=? AND institution_id=?", (version_id, inst_id)).fetchone()
    if not ver:
        raise HTTPException(404, "Policy version not found")
    latest = current_version(conn, inst_id, ver["course_id"])
    if latest["id"] != ver["id"]:
        raise HTTPException(400, "Only the current version can be reminded")
    if not _smtp_settings(conn, inst_id):
        raise HTTPException(400, "Email isn't set up for this company. Turn on email notifications under Settings → Notifications first.")
    course = conn.execute("SELECT title FROM ld_courses WHERE id=?", (ver["course_id"],)).fetchone()
    today = today_for_institution(conn, inst_id)
    app_url = os.environ.get("APP_BASE_URL", "https://ems-app.fly.dev")
    recent = last_reminded_map(conn, inst_id, version_id)
    cutoff = _cooldown_cutoff(MANUAL_REMIND_COOLDOWN_DAYS)
    rows = conn.execute("""
        SELECT a.employee_id, e.full_name, e.work_email, e.personal_email
        FROM policy_acknowledgements a
        JOIN employees e ON e.employee_id=a.employee_id AND e.institution_id=a.institution_id AND e.status='Active'
        WHERE a.version_id=? AND a.institution_id=? AND a.acknowledged_at IS NULL ORDER BY e.full_name
    """, (version_id, inst_id)).fetchall()
    queued = skipped_recent = no_email = 0
    for r in rows:
        if recent.get(r["employee_id"], "") >= cutoff:
            skipped_recent += 1
            continue
        email = r["work_email"] or r["personal_email"]
        if not email:
            no_email += 1
            continue
        subject, body = reminder_email(course["title"], ver["version"], ver["due_date"], today, r["full_name"], app_url)
        queue_email(conn, inst_id, email, subject, body, REMINDER_CATEGORY, "policy",
                    reminder_dedupe_key(version_id, r["employee_id"]))
        queued += 1
    write_entity_audit(conn, user, inst_id, "L&D", "policy", ver["course_id"], "Reminders sent",
                       detail=f"v{ver['version']}: reminder emailed to {queued} employee(s)", entity_label=course["title"])
    conn.commit()
    return {"queued": queued, "skipped_recent": skipped_recent, "no_email": no_email}


@router.get("/api/policies/{course_id}/export.csv")
@db_session
def export_policy_csv(conn, course_id: int, version_id: Optional[int] = None, user: dict = Depends(get_current_user)):
    """The acknowledgement record for one version as a CSV (audit evidence). HR gets everyone, a manager
    their own team. Times are in the company's own timezone."""
    inst_id = need_inst(user)
    _, scope_sql, scope_params = _scope(conn, inst_id, user)
    course = _get_policy(conn, inst_id, course_id)
    if version_id:
        ver = conn.execute("SELECT * FROM policy_versions WHERE id=? AND course_id=? AND institution_id=?",
                           (version_id, course_id, inst_id)).fetchone()
    else:
        ver = current_version(conn, inst_id, course_id)
    if not ver:
        raise HTTPException(404, "Policy version not found")
    from zoneinfo import ZoneInfo
    from datetime import timezone as _tz
    tzrow = conn.execute("SELECT timezone FROM institutions WHERE id=?", (inst_id,)).fetchone()
    try:
        tz = ZoneInfo((tzrow["timezone"] if tzrow else None) or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")

    def local(ts):
        if not ts:
            return ""
        return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=_tz.utc).astimezone(tz).strftime("%Y-%m-%d %H:%M")

    today = today_for_institution(conn, inst_id)
    acks = conn.execute(
        f"""SELECT a.*, e.full_name, e.department FROM policy_acknowledgements a
            LEFT JOIN employees e ON e.employee_id=a.employee_id AND e.institution_id=a.institution_id
            WHERE a.version_id=?{scope_sql} ORDER BY e.full_name""", [ver["id"], *scope_params]
    ).fetchall()
    labels = {"acknowledged": "Acknowledged", "overdue": "Overdue", "opened": "Opened, not acknowledged", "not_opened": "Not opened"}
    header = ["Employee ID", "Name", "Department", "Policy", "Version", "Due", "Status", "Assigned", "Opened", "Acknowledged", "Statement"]
    lines = [",".join(csv_cell(h) for h in header)]
    for a in acks:
        lines.append(",".join(csv_cell(v) for v in [
            a["employee_id"], a["full_name"], a["department"], course["title"], f"v{ver['version']}", ver["due_date"] or "",
            labels[ack_status(a, ver["due_date"], today)], local(a["assigned_at"]), local(a["first_opened_at"]),
            local(a["acknowledged_at"]), a["statement"] or ""]))
    safe = "".join(ch if ch.isalnum() else "-" for ch in course["title"]).strip("-")[:60] or "policy"
    return Response(
        content="\ufeff" + "\r\n".join(lines) + "\r\n", media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}-v{ver["version"]}-acknowledgements.csv"',
                 "Cache-Control": "private, no-store"})
