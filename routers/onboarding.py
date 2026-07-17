"""Onboarding / Offboarding — Templates and Checklists."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from core.deps import get_current_user, need_inst, require_roles
except ImportError:
    from ems.core.deps import get_current_user, need_inst, require_roles

try:
    from core.org_queries import subordinates_in_clause, is_self_or_subordinate
except ImportError:
    from ems.core.org_queries import subordinates_in_clause, is_self_or_subordinate

try:
    from core.ob_ld_shared import log_ob, auto_enroll_ld_course
except ImportError:
    from ems.core.ob_ld_shared import log_ob, auto_enroll_ld_course

try:
    from db import get_db
except ImportError:
    from ems.db import get_db

try:
    from core.db_session import db_session
except ImportError:
    from ems.core.db_session import db_session

router = APIRouter()

OB_ROLES = ["employee", "manager", "hr_admin", "hr_manager"]
OB_MANAGE_ROLES = ("superadmin", "hr_manager", "hr_admin")


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


# ---------------------------------------------------------------------------
# Onboarding / Offboarding — Templates
# ---------------------------------------------------------------------------
@router.get("/api/ob/templates")
@db_session
def list_ob_templates(conn, type: Optional[str] = None, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    q = "SELECT * FROM ob_templates WHERE institution_id=? AND is_active=1"
    p = [inst_id]
    if type:
        q += " AND type=?"; p.append(type)
    q += " ORDER BY type, order_index"
    rows = conn.execute(q, p).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/ob/templates", status_code=201)
@db_session
def create_ob_template(conn, body: OBTemplateIn, user: dict = Depends(require_roles(*OB_MANAGE_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if body.type not in ("onboarding","offboarding"):
        raise HTTPException(400, "type must be onboarding or offboarding")
    if body.assigned_role not in OB_ROLES:
        raise HTTPException(400, f"assigned_role must be one of: {', '.join(OB_ROLES)}")
    conn.execute(
        "INSERT INTO ob_templates (institution_id,type,title,description,assigned_role,order_index,linked_ld_course_id) VALUES (?,?,?,?,?,?,?)",
        (inst_id, body.type, body.title, body.description, body.assigned_role, body.order_index, body.linked_ld_course_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM ob_templates WHERE id=last_insert_rowid()").fetchone()
    return dict(row)


@router.put("/api/ob/templates/{tmpl_id}")
@db_session
def update_ob_template(conn, tmpl_id: int, body: OBTemplateIn, user: dict = Depends(require_roles(*OB_MANAGE_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM ob_templates WHERE id=? AND institution_id=?", (tmpl_id, inst_id)).fetchone():
        raise HTTPException(404, "Template not found")
    conn.execute(
        "UPDATE ob_templates SET title=?,description=?,assigned_role=?,order_index=?,linked_ld_course_id=? WHERE id=?",
        (body.title, body.description, body.assigned_role, body.order_index, body.linked_ld_course_id, tmpl_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM ob_templates WHERE id=?", (tmpl_id,)).fetchone()
    return dict(row)


@router.delete("/api/ob/templates/{tmpl_id}", status_code=204)
@db_session
def delete_ob_template(conn, tmpl_id: int, user: dict = Depends(require_roles(*OB_MANAGE_ROLES))) -> None:
    inst_id = need_inst(user)
    conn.execute("UPDATE ob_templates SET is_active=0 WHERE id=? AND institution_id=?", (tmpl_id, inst_id))
    conn.commit()


# ---------------------------------------------------------------------------
# Onboarding / Offboarding — Checklists
# ---------------------------------------------------------------------------
@router.get("/api/ob/checklists")
@db_session
def list_ob_checklists(conn, type: Optional[str] = None, status: Optional[str] = None,
                       user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
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
        frag, fp = subordinates_in_clause(inst_id, user.get("employee_id", ""))
        q += f" AND e.employee_id IN {frag}"; p.extend(fp)
    elif user["role"] == "employee":
        q += " AND c.employee_id=?"; p.append(user.get("employee_id",""))
    q += " GROUP BY c.id, e.full_name, e.department, e.designation ORDER BY c.created_at DESC"
    rows = conn.execute(q, p).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/ob/checklists", status_code=201)
@db_session
def start_ob_checklist(conn, body: OBChecklistStartIn, user: dict = Depends(require_roles(*OB_MANAGE_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if body.type not in ("onboarding","offboarding"):
        raise HTTPException(400, "type must be onboarding or offboarding")
    # Check employee exists
    emp = conn.execute("SELECT * FROM employees WHERE employee_id=? AND institution_id=?",
                       (body.employee_id, inst_id)).fetchone()
    if not emp:
        raise HTTPException(404, "Employee not found")
    # Check not already active
    existing = conn.execute(
        "SELECT id FROM ob_checklists WHERE employee_id=? AND institution_id=? AND type=? AND status='In Progress'",
        (body.employee_id, inst_id, body.type)
    ).fetchone()
    if existing:
        raise HTTPException(400, f"An active {body.type} checklist already exists for this employee")
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
            enrollment_id = auto_enroll_ld_course(conn, inst_id, body.employee_id, t["linked_ld_course_id"], user)
        conn.execute(
            "INSERT INTO ob_checklist_items (checklist_id,institution_id,template_id,title,description,assigned_role,order_index,linked_ld_course_id,linked_ld_enrollment_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (cl_id, inst_id, t["id"], t["title"], t["description"], t["assigned_role"], t["order_index"],
             t["linked_ld_course_id"], enrollment_id)
        )
    log_ob(conn, inst_id, cl_id, body.employee_id, body.type,
           "Checklist Started",
           f"{body.type.capitalize()} checklist started for {emp['full_name']} with {len(templates)} items",
           user)
    conn.commit()
    row = conn.execute("SELECT * FROM ob_checklists WHERE id=?", (cl_id,)).fetchone()
    return dict(row)


@router.get("/api/ob/checklists/{cl_id}")
@db_session
def get_ob_checklist(conn, cl_id: int, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    cl = conn.execute(
        "SELECT c.*, e.full_name AS employee_name, e.department, e.designation FROM ob_checklists c JOIN employees e ON e.employee_id=c.employee_id AND e.institution_id=c.institution_id WHERE c.id=? AND c.institution_id=?",
        (cl_id, inst_id)
    ).fetchone()
    if not cl:
        raise HTTPException(404, "Checklist not found")
    if user["role"] == "employee" and cl["employee_id"] != user.get("employee_id"):
        raise HTTPException(403, "Access denied to this checklist")
    if user["role"] == "manager" and not is_self_or_subordinate(conn, inst_id, user.get("employee_id"), cl["employee_id"]):
        raise HTTPException(403, "Access denied to this checklist")
    items = conn.execute(
        "SELECT * FROM ob_checklist_items WHERE checklist_id=? ORDER BY order_index",
        (cl_id,)
    ).fetchall()
    result = dict(cl)
    # Employees only see items assigned to their own role — hide other roles' tasks/notes
    if user["role"] == "employee":
        items = [i for i in items if i["assigned_role"] == "employee"]
    result["items"] = [dict(i) for i in items]
    return result


@router.patch("/api/ob/checklists/{cl_id}/items/{item_id}")
@db_session
def update_ob_item(conn, cl_id: int, item_id: int, body: OBItemUpdateIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if body.status not in ("Pending","Done","N/A"):
        raise HTTPException(400, "status must be Pending, Done or N/A")
    cl = conn.execute("SELECT * FROM ob_checklists WHERE id=? AND institution_id=?", (cl_id, inst_id)).fetchone()
    if not cl:
        raise HTTPException(404, "Checklist not found")
    item = conn.execute("SELECT * FROM ob_checklist_items WHERE id=? AND checklist_id=?", (item_id, cl_id)).fetchone()
    if not item:
        raise HTTPException(404, "Item not found")
    # Permission: assigned_role must match user role, or HR manager/admin can override
    can_act = (item["assigned_role"] == user["role"] or user["role"] in ("superadmin","hr_manager","hr_admin"))
    if not can_act:
        raise HTTPException(403, f"This item is assigned to {item['assigned_role']}")
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
    log_ob(conn, inst_id, cl_id, cl["employee_id"], cl["type"],
           "Item Updated",
           f"'{item['title']}' changed from {prev_status} → {body.status}" +
           (f" (note: {body.notes})" if body.notes else ""),
           user)
    if auto_completed:
        log_ob(conn, inst_id, cl_id, cl["employee_id"], cl["type"],
               "Checklist Completed",
               f"All {total} items completed — checklist auto-closed",
               user)
    conn.commit()
    return {"ok": True}


@router.delete("/api/ob/checklists/{cl_id}", status_code=204)
@db_session
def delete_ob_checklist(conn, cl_id: int, user: dict = Depends(require_roles(*OB_MANAGE_ROLES))) -> None:
    inst_id = need_inst(user)
    cl = conn.execute("SELECT * FROM ob_checklists WHERE id=? AND institution_id=?", (cl_id, inst_id)).fetchone()
    if cl:
        log_ob(conn, inst_id, cl_id, cl["employee_id"], cl["type"],
               "Checklist Deleted", "Checklist and all items removed", user)
        conn.commit()
    conn.execute("DELETE FROM ob_checklist_items WHERE checklist_id=?", (cl_id,))
    conn.execute("DELETE FROM ob_checklists WHERE id=? AND institution_id=?", (cl_id, inst_id))
    conn.commit()


@router.put("/api/ob/checklists/{cl_id}/items/{item_id}")
@db_session
def edit_ob_item(conn, cl_id: int, item_id: int, body: OBItemEditIn,
                 user: dict = Depends(require_roles(*OB_MANAGE_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM ob_checklists WHERE id=? AND institution_id=?", (cl_id, inst_id)).fetchone():
        raise HTTPException(404, "Checklist not found")
    if not conn.execute("SELECT id FROM ob_checklist_items WHERE id=? AND checklist_id=?", (item_id, cl_id)).fetchone():
        raise HTTPException(404, "Item not found")
    if body.assigned_role not in OB_ROLES:
        raise HTTPException(400, f"assigned_role must be one of: {', '.join(OB_ROLES)}")
    old = conn.execute("SELECT * FROM ob_checklist_items WHERE id=? AND checklist_id=?", (item_id, cl_id)).fetchone()
    cl2 = conn.execute("SELECT * FROM ob_checklists WHERE id=?", (cl_id,)).fetchone()
    conn.execute(
        "UPDATE ob_checklist_items SET title=?,description=?,assigned_role=? WHERE id=?",
        (body.title, body.description, body.assigned_role, item_id)
    )
    if cl2:
        log_ob(conn, inst_id, cl_id, cl2["employee_id"], cl2["type"],
               "Item Edited",
               f"'{old['title'] if old else item_id}' → title='{body.title}', role={body.assigned_role}",
               user)
    conn.commit()
    return {"ok": True}


@router.post("/api/ob/checklists/{cl_id}/items", status_code=201)
@db_session
def add_ob_item(conn, cl_id: int, body: OBItemAddIn,
                user: dict = Depends(require_roles(*OB_MANAGE_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    cl = conn.execute("SELECT * FROM ob_checklists WHERE id=? AND institution_id=?", (cl_id, inst_id)).fetchone()
    if not cl:
        raise HTTPException(404, "Checklist not found")
    if body.assigned_role not in OB_ROLES:
        raise HTTPException(400, f"assigned_role must be one of: {', '.join(OB_ROLES)}")
    max_order = conn.execute("SELECT MAX(order_index) FROM ob_checklist_items WHERE checklist_id=?", (cl_id,)).fetchone()[0] or 0
    enrollment_id = None
    if body.linked_ld_course_id:
        enrollment_id = auto_enroll_ld_course(conn, inst_id, cl["employee_id"], body.linked_ld_course_id, user)
    conn.execute(
        "INSERT INTO ob_checklist_items (checklist_id,institution_id,title,description,assigned_role,order_index,linked_ld_course_id,linked_ld_enrollment_id) VALUES (?,?,?,?,?,?,?,?)",
        (cl_id, inst_id, body.title, body.description, body.assigned_role, max_order + 1,
         body.linked_ld_course_id, enrollment_id)
    )
    row = conn.execute("SELECT * FROM ob_checklist_items WHERE id=last_insert_rowid()").fetchone()
    log_ob(conn, inst_id, cl_id, cl["employee_id"], cl["type"],
           "Item Added", f"New item '{body.title}' assigned to {body.assigned_role}", user)
    conn.commit()
    return dict(row)


@router.delete("/api/ob/checklists/{cl_id}/items/{item_id}", status_code=204)
@db_session
def delete_ob_item(conn, cl_id: int, item_id: int,
                   user: dict = Depends(require_roles(*OB_MANAGE_ROLES))) -> None:
    inst_id = need_inst(user)
    cl = conn.execute("SELECT * FROM ob_checklists WHERE id=? AND institution_id=?", (cl_id, inst_id)).fetchone()
    item = conn.execute("SELECT * FROM ob_checklist_items WHERE id=? AND checklist_id=?", (item_id, cl_id)).fetchone()
    if not cl:
        raise HTTPException(404, "Checklist not found")
    if item and cl:
        log_ob(conn, inst_id, cl_id, cl["employee_id"], cl["type"],
               "Item Removed", f"Item '{item['title']}' removed from checklist", user)
        conn.commit()
    conn.execute("DELETE FROM ob_checklist_items WHERE id=? AND checklist_id=?", (item_id, cl_id))
    conn.commit()


@router.get("/api/employees/{employee_id}/ob-history")
@db_session
def get_employee_ob_history(conn, employee_id: str, user: dict = Depends(require_roles(*OB_MANAGE_ROLES))) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    rows = conn.execute(
        "SELECT * FROM ob_audit_log WHERE employee_id=? AND institution_id=? ORDER BY created_at ASC",
        (employee_id, inst_id)
    ).fetchall()
    return [dict(r) for r in rows]
