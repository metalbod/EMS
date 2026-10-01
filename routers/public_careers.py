"""Public (no-login) job application endpoints — the only place in this app
a web visitor can write institution-scoped data without a JWT
(core/deps.py's get_current_user) or a pre-shared device key
(routers/attendance.py's get_device). Institution/tenant scoping is
resolved from job_requisitions.public_token (a random UUID, generated only
when HR explicitly enables public applications for an Approved requisition
— see enable_public_link/disable_public_link in routers/recruitment.py) or
from institutions.code (already a public-facing identifier — it's what
every employee types into the login screen's "Company Code" field) for the
listing page, rather than from any logged-in user. Nothing here calls
core/permission_matrix.py's require_permission — there is no user to check
permissions for.

Logged-in internal applicants use these SAME endpoints, not a separate
flow — see resolve_public_requisition's internal-source detection below.

Deliberately does NOT offer any "is this an existing candidate?" check or
prompt back to the caller (unlike the HR-facing Add Candidate duplicate-
detection panel in routers/recruitment.py's search_candidates) — telling an
anonymous visitor "we already have a candidate with this email" would leak
who else is in the system. The matching in submit_public_application is
silent: same email within the institution reuses that candidate_id, a new
email creates a new one, and the response is identical either way.

Rate limiting and Turnstile verification both deliberately run AFTER the
token/institution resolution and BEFORE any DB write, so a request that
fails either check never touches candidates/candidate_requisitions at all.
"""
import os
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from core.deps import decode_token
from core.validators import validate_public_resume_data_url
from db import get_db, set_rls_context, IntegrityError
from core.db_session import db_session

router = APIRouter()

PUBLIC_APPLY_MAX_PER_HOUR = 10
PUBLIC_APPLY_WINDOW_SECONDS = 3600
# In-memory, per-process sliding window — same deliberate choice and same
# caveat as routers/auth.py's login rate limiter (this app runs as a single
# uvicorn worker/machine today; move to Redis if that ever changes). Keyed
# on IP alone (not IP+something-identifying, since there's no username
# equivalent here) — a NAT'd office full of real applicants sharing one
# public IP is the known false-positive case, same tradeoff login's own
# limiter accepts for the same reason.
_apply_attempts: Dict[str, deque] = defaultdict(deque)

TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY")
# Safe to hand to the browser — unlike the secret key above, Cloudflare's
# own docs say the site key is meant to be public. Returned as part of the
# apply-form response so the frontend only renders the widget (and loads
# Cloudflare's script) when CAPTCHA is actually configured — see
# static/js/public_careers.js's loadTurnstileWidget.
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY")
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _enforce_public_apply_rate_limit(request: Request) -> None:
    ip = _client_ip(request)
    now = time.monotonic()
    attempts = _apply_attempts[ip]
    while attempts and now - attempts[0] > PUBLIC_APPLY_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= PUBLIC_APPLY_MAX_PER_HOUR:
        retry_after = max(1, int(PUBLIC_APPLY_WINDOW_SECONDS - (now - attempts[0])))
        raise HTTPException(429, f"Too many applications from this connection. Try again in {retry_after} seconds.")
    attempts.append(now)


def _verify_turnstile(token: Optional[str], request: Request) -> None:
    """Fails open (skips verification) when TURNSTILE_SECRET_KEY isn't
    configured, so local dev and the test suite don't need a real
    Cloudflare account — see CLAUDE.md for where to set it before this
    goes live publicly. Fails closed (rejects the submission) on any other
    problem: a missing token, a Cloudflare-reported failure, or
    Cloudflare's own endpoint being unreachable — unlike the rate limiter
    above, a broken CAPTCHA check must not silently let every submission
    through."""
    if not TURNSTILE_SECRET_KEY:
        return
    if not token:
        raise HTTPException(400, "Please complete the verification challenge.")
    try:
        resp = requests.post(TURNSTILE_VERIFY_URL, data={
            "secret": TURNSTILE_SECRET_KEY,
            "response": token,
            "remoteip": _client_ip(request),
        }, timeout=5)
        ok = resp.ok and resp.json().get("success") is True
    except requests.RequestException:
        ok = False
    if not ok:
        raise HTTPException(400, "Verification failed. Please try again.")


def _optional_internal_institution_id(request: Request) -> Optional[int]:
    """Best-effort "is this applicant logged in?" check — never raises, so
    a missing/expired/malformed token just means "treat as external",
    exactly like an anonymous visitor. Deliberately NOT core/deps.py's
    get_current_user (which requires a valid token and raises 401 without
    one) — this endpoint has no auth requirement at all; a logged-in
    session only changes how the resulting application is tagged."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        payload = decode_token(auth[len("Bearer "):])
    except HTTPException:
        return None
    return payload.get("institution_id")


async def resolve_public_requisition(token: str) -> dict:
    """The institution/tenant-scoping resolution every endpoint below
    depends on. Must stay `async def` with these DB calls made directly
    (not via asyncio.to_thread, not @db_session) — set_rls_context's
    ContextVar only propagates to this request's LATER get_db() calls if
    the mutation happens on the request's own asyncio task, exactly the
    constraint routers/attendance.py's get_device documents and relies on
    for the same reason. The first query below runs under this context's
    default (bypass_rls=True, since nothing has called set_rls_context yet
    in this fresh request) — safe here because it's filtered to an exact,
    unguessable UUID match, the same reasoning get_device applies to its
    own pre-context device-key lookup."""
    conn = get_db()
    try:
        req = conn.execute(
            "SELECT id, institution_id, title, department, employment_type, "
            "description, requirements, status FROM job_requisitions WHERE public_token=?",
            (token,)
        ).fetchone()
        if not req or req["status"] != "Approved":
            raise HTTPException(404, "This job posting is no longer available.")
        set_rls_context(req["institution_id"], bypass_rls=False)
        return dict(req)
    finally:
        conn.close()


@router.get("/api/public/careers/{institution_code}")
async def list_public_careers(institution_code: str) -> Dict[str, Any]:
    conn = get_db()
    try:
        inst = conn.execute(
            "SELECT id, name FROM institutions WHERE code=? AND status='Active'",
            (institution_code.strip().upper(),)
        ).fetchone()
        if not inst:
            raise HTTPException(404, "Not found")
        set_rls_context(inst["id"], bypass_rls=False)
        rows = conn.execute(
            "SELECT title, department, employment_type, public_token FROM job_requisitions "
            "WHERE institution_id=? AND status='Approved' AND public_token IS NOT NULL "
            "ORDER BY created_at DESC",
            (inst["id"],)
        ).fetchall()
        return {"institution_name": inst["name"], "positions": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/api/public/careers/apply/{token}")
async def get_public_requisition(req: dict = Depends(resolve_public_requisition)) -> Dict[str, Any]:
    data = {k: req[k] for k in ("title", "department", "employment_type", "description", "requirements")}
    data["turnstile_site_key"] = TURNSTILE_SITE_KEY
    return data


class PublicApplyIn(BaseModel):
    full_name: str
    email: str
    phone: Optional[str] = None
    ic_number: Optional[str] = None
    cover_note: Optional[str] = None
    resume_file_name: Optional[str] = None
    resume_mime_type: Optional[str] = None
    resume_data_url: Optional[str] = None
    turnstile_token: Optional[str] = None

    @field_validator("resume_data_url")
    @classmethod
    def _validate_resume(cls, v):
        return validate_public_resume_data_url(v)


@router.post("/api/public/careers/apply/{token}", status_code=201)
@db_session
def submit_public_application(conn, request: Request, body: PublicApplyIn,
                               req: dict = Depends(resolve_public_requisition)) -> Dict[str, Any]:
    _enforce_public_apply_rate_limit(request)
    _verify_turnstile(body.turnstile_token, request)

    inst_id = req["institution_id"]
    req_id = req["id"]
    internal_inst_id = _optional_internal_institution_id(request)
    source = "Internal" if internal_inst_id == inst_id else "Direct"

    # Silent match-by-email within this institution — see this module's
    # docstring. Never surfaced to the caller either way.
    existing = conn.execute(
        "SELECT id FROM candidates WHERE institution_id=? AND email IS NOT NULL AND LOWER(email)=LOWER(?)",
        (inst_id, body.email)
    ).fetchone()
    if existing:
        cand_id = existing["id"]
    else:
        conn.execute("""
            INSERT INTO candidates (institution_id,full_name,email,phone,ic_number,created_by)
            VALUES (?,?,?,?,?,?)
        """, (inst_id, body.full_name, body.email, body.phone, body.ic_number, "Public Application"))
        cand_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    try:
        conn.execute("""
            INSERT INTO candidate_requisitions (institution_id,candidate_id,requisition_id,source,notes,created_by)
            VALUES (?,?,?,?,?,?)
        """, (inst_id, cand_id, req_id, source, body.cover_note, "Public Application"))
    except IntegrityError:
        # Already applied to this exact job (resubmitted the form, double
        # click, etc) — same generic response either way, no disclosure.
        conn.rollback()
        return {"ok": True, "message": "Application received"}

    if body.resume_data_url:
        conn.execute("""
            INSERT INTO candidate_documents (institution_id,candidate_id,file_name,mime_type,data_url,uploaded_by)
            VALUES (?,?,?,?,?,?)
        """, (inst_id, cand_id, body.resume_file_name or "resume", body.resume_mime_type or "application/pdf",
              body.resume_data_url, "Public Application"))

    conn.execute(
        "INSERT INTO candidate_audit_log (institution_id,candidate_id,action,detail,performed_by) VALUES (?,?,?,?,?)",
        (inst_id, cand_id, "Applied", f"Applied via public job posting ({source})", "Public Application")
    )
    conn.commit()
    return {"ok": True, "message": "Application received"}
