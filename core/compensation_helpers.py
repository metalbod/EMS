"""Small helper shared across every Compensation sub-router (pay structure,
merit, bonus, commission, equity, rewards — see routers/compensation_*.py).
Split out when routers/compensation.py itself was split by concern."""
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
