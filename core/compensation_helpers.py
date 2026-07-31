"""Small helpers shared across every Compensation sub-router (pay structure,
merit, bonus, commission, equity, rewards — see routers/compensation_*.py).
Split out when routers/compensation.py itself was split by concern; these
two are the only things every sub-domain actually needed in common."""
from fastapi import HTTPException


def require_hr_role(current_user: dict):
    """Require HR Manager, Payroll Manager, or Compensation Manager role.

    Deliberately excludes hr_admin (previously included) — matches the
    frontend nav visibility change, so this isn't just a hidden menu with
    the API still wide open to a role that shouldn't see it.

    compensation_manager is a module-scoped role — full access here, but
    (by design, via omission from every other router's own role allow-list)
    no access to unrelated modules like payroll runs, recruitment, etc."""
    if current_user.get("role") not in ["superadmin", "hr_manager", "payroll_manager", "compensation_manager"]:
        raise HTTPException(403, detail="HR Manager, Payroll Manager, or Compensation Manager access required")


def add_hr_note(conn, inst_id: int, employee_id: str, body: str, username: str):
    """Log a compensation event (merit recommendation created/decided, salary
    adjusted) as an HR note on the employee's record, so it shows up in the
    same history HR already reviews on the employee profile — matches the
    existing note_type values used by routers/hr_notes.py's UI dropdown
    (General/Disciplinary/Performance/Warning/Commendation)."""
    conn.execute(
        "INSERT INTO hr_notes (institution_id, employee_id, note_type, body, created_by) VALUES (?, ?, ?, ?, ?)",
        (inst_id, employee_id, "performance", body, username),
    )
