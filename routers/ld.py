"""Learning & Development: Courses, Enrollments, Quizzes, and Course Modules (content)."""
import random
from typing import List, Optional

import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from core.deps import get_current_user, need_inst, require_roles
except ImportError:
    from ems.core.deps import get_current_user, need_inst, require_roles

try:
    from core.org_queries import subordinates_in_clause
except ImportError:
    from ems.core.org_queries import subordinates_in_clause

try:
    from core.ob_ld_shared import log_ld, complete_linked_ob_items
except ImportError:
    from ems.core.ob_ld_shared import log_ld, complete_linked_ob_items

try:
    from db import get_db, IntegrityError
except ImportError:
    from ems.db import get_db, IntegrityError

router = APIRouter()

LD_MANAGE_ROLES = ("superadmin", "hr_manager", "hr_admin")
LD_CATEGORIES = ("mandatory", "professional_development", "certification")


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


# ---------------------------------------------------------------------------
# Learning & Development — Courses
# ---------------------------------------------------------------------------
@router.get("/api/ld/courses")
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


@router.post("/api/ld/courses", status_code=201)
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


@router.put("/api/ld/courses/{course_id}")
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


@router.delete("/api/ld/courses/{course_id}", status_code=204)
def delete_ld_course(course_id: int, user: dict = Depends(require_roles(*LD_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    conn.execute("UPDATE ld_courses SET is_active=0 WHERE id=? AND institution_id=?", (course_id, inst_id))
    conn.commit(); conn.close()


# ---------------------------------------------------------------------------
# Learning & Development — Enrollments
# ---------------------------------------------------------------------------
@router.get("/api/ld/enrollments")
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
        frag, fp = subordinates_in_clause(inst_id, user.get("employee_id", ""))
        q += f" AND e.employee_id IN {frag}"; p.extend(fp)
    elif user["role"] == "employee":
        q += " AND en.employee_id=?"; p.append(user.get("employee_id", ""))
    q += " ORDER BY en.created_at DESC"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/ld/enrollments", status_code=201)
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
    log_ld(conn, inst_id, enr_id, body.employee_id, "Enrolled",
           f"Enrolled in '{course['title']}' — status: {status}", user)
    conn.commit()
    row = conn.execute("SELECT * FROM ld_enrollments WHERE id=?", (enr_id,)).fetchone()
    conn.close()
    return dict(row)


@router.patch("/api/ld/enrollments/{enr_id}/status")
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
        log_ld(conn, inst_id, enr_id, enr["employee_id"], f"Enrollment {body.status}",
               f"{body.notes or ''}".strip() or f"Enrollment {body.status.lower()} by {user['username']}", user)
    elif body.status == "Completed":
        if user["role"] == "employee" and user.get("employee_id") != enr["employee_id"]:
            conn.close(); raise HTTPException(403, "Access denied")
        conn.execute(
            "UPDATE ld_enrollments SET status='Completed', completed_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=?",
            (enr_id,)
        )
        log_ld(conn, inst_id, enr_id, enr["employee_id"], "Completed",
               f"Marked complete by {user['username']}", user)
        complete_linked_ob_items(conn, inst_id, enr["employee_id"], enr["course_id"], user)
    else:
        conn.execute("UPDATE ld_enrollments SET status=? WHERE id=?", (body.status, enr_id))
        log_ld(conn, inst_id, enr_id, enr["employee_id"], "Status Updated",
               f"Status changed to {body.status}", user)

    conn.commit()
    row = conn.execute("SELECT * FROM ld_enrollments WHERE id=?", (enr_id,)).fetchone()
    conn.close()
    return dict(row)


@router.get("/api/employees/{employee_id}/ld-history")
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


@router.get("/api/ld/courses/{course_id}/quiz")
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


@router.get("/api/ld/courses/{course_id}/quiz/manage")
def get_course_quiz_for_manage(course_id: int, user: dict = Depends(require_roles(*LD_MANAGE_ROLES))):
    """Returns the quiz with correct answers included, for HR to edit."""
    inst_id = need_inst(user)
    conn = get_db()
    quiz = _quiz_for_course(conn, inst_id, course_id)
    conn.close()
    if not quiz:
        raise HTTPException(404, "No quiz for this course")
    return quiz


@router.put("/api/ld/courses/{course_id}/quiz")
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


@router.delete("/api/ld/courses/{course_id}/quiz", status_code=204)
def delete_course_quiz(course_id: int, user: dict = Depends(require_roles(*LD_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    quiz = conn.execute("SELECT id FROM ld_quizzes WHERE course_id=? AND institution_id=?", (course_id, inst_id)).fetchone()
    if quiz:
        conn.execute("DELETE FROM ld_quiz_questions WHERE quiz_id=?", (quiz["id"],))
        conn.execute("DELETE FROM ld_quizzes WHERE id=?", (quiz["id"],))
        conn.commit()
    conn.close()


@router.post("/api/ld/quizzes/{quiz_id}/attempts", status_code=201)
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
        log_ld(conn, inst_id, enrollment["id"], enrollment["employee_id"], "Quiz Passed",
               f"Scored {score}% on '{quiz['title']}' (attempt {prior_attempts+1}) — course completed", user)
        complete_linked_ob_items(conn, inst_id, enrollment["employee_id"], quiz["course_id"], user)
    else:
        log_ld(conn, inst_id, enrollment["id"], enrollment["employee_id"], "Quiz Attempt Failed",
               f"Scored {score}% on '{quiz['title']}' (attempt {prior_attempts+1}, needed {quiz['pass_threshold']}%)", user)
    conn.commit()
    conn.close()
    return {"score": score, "passed": passed, "attempt_number": prior_attempts + 1, "max_attempts": quiz["max_attempts"]}


@router.get("/api/ld/quizzes/{quiz_id}/attempts")
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
@router.get("/api/ld/courses/{course_id}/modules")
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


@router.put("/api/ld/courses/{course_id}/modules")
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


@router.post("/api/ld/enrollments/{enr_id}/modules/{module_id}/viewed", status_code=201)
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
